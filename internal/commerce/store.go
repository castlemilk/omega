package commerce

import (
	"bytes"
	"context"
	"database/sql"
	_ "embed"
	"errors"
	"fmt"
	"net"
	"net/url"
	"path"
	"strings"
	"time"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/google/uuid"
	"google.golang.org/protobuf/proto"
)

//go:embed schema.sql
var schema string

var (
	ErrMissing      = errors.New("order unavailable for this buyer")
	ErrBlocked      = errors.New("this order has no current download entitlement")
	ErrConflict     = errors.New("order reference requires reconciliation")
	ErrInvalidEvent = errors.New("unverified provider event")
)

const downloadLifetime = 24 * time.Hour

type Shop struct {
	db                                                  *sql.DB
	connection, offerID, edition, origin, webhookSecret string
	provider                                            Provider
}

func Open(ctx context.Context, db *sql.DB, account, origin, signingSecret string, provider Provider, offer *v1.DigitalOffer, archive []byte) (*Shop, error) {
	u, err := url.Parse(origin)
	if err != nil || u.Scheme != "http" || !net.ParseIP(u.Hostname()).IsLoopback() || u.User != nil || u.Path != "" || u.RawQuery != "" || u.Fragment != "" || db == nil {
		return nil, errors.New("the sandbox requires a local origin and order database")
	}
	if !strings.HasPrefix(account, "acct_") || !strings.HasPrefix(signingSecret, "whsec_") || provider == nil || offer.GetBusinessId() == "" ||
		offer.GetProductId() == "" || offer.Edition == "" || len(offer.PacketSha256) != 64 || offer.Licence == "" ||
		len(archive) == 0 || len(archive) > 20<<20 || offer.ArchiveSha256 != fingerprint(archive) || offer.ArchiveName != path.Base(offer.ArchiveName) ||
		!strings.HasSuffix(offer.ArchiveName, ".zip") || offer.AmountMinor <= 0 || len(offer.Currency) != 3 {
		return nil, errors.New("incomplete test connection or immutable offer")
	}
	s := &Shop{db: db, connection: account + "/" + offer.BusinessId, offerID: offerKey(offer), edition: offer.Edition, origin: origin, webhookSecret: signingSecret, provider: provider}
	// Serialise first-start DDL across processes. DDL and the immutable offer
	// become visible together. An order always retains its original offer key.
	tx, err := db.BeginTx(ctx, nil)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()
	if _, err = tx.ExecContext(ctx, "SELECT pg_advisory_xact_lock(7142586001)"); err != nil {
		return nil, err
	}
	if _, err = tx.ExecContext(ctx, schema); err != nil {
		return nil, err
	}
	body, err := proto.MarshalOptions{Deterministic: true}.Marshal(offer)
	if err != nil {
		return nil, err
	}
	_, err = tx.ExecContext(ctx, `INSERT INTO omega_digital_offers(connection_id,offer_key,definition,archive) VALUES($1,$2,$3,$4) ON CONFLICT DO NOTHING`, s.connection, s.offerID, body, archive)
	if err != nil {
		return nil, err
	}
	var stored, pack []byte
	if err = tx.QueryRowContext(ctx, `SELECT definition,archive FROM omega_digital_offers WHERE connection_id=$1 AND offer_key=$2`, s.connection, s.offerID).Scan(&stored, &pack); err != nil {
		return nil, err
	}
	if !bytes.Equal(body, stored) || !bytes.Equal(pack, archive) {
		return nil, ErrConflict
	}
	return s, tx.Commit()
}

type order struct {
	id, offerID, session, url, payment, charge, dispute string
	buyer                                               []byte
	offer                                               *v1.DigitalOffer
	created                                             time.Time
	entitled, verified                                  sql.NullTime
	state                                               v1.DigitalPaymentState
	refunded                                            int64
	downloads                                           uint32
	open                                                bool
}
type queryer interface {
	QueryRowContext(context.Context, string, ...any) *sql.Row
}

func (s *Shop) order(ctx context.Context, q queryer, id string, buyer []byte, lock bool) (order, error) {
	var a order
	stmt := `SELECT o.id,o.offer_key,o.buyer_hash,o.created_at,coalesce(o.session_id,''),o.checkout_url,o.payment_id,o.charge_id,o.payment,o.refunded,o.dispute,o.entitled_at,o.verified_at,o.downloads,o.checkout_open,f.definition
		FROM omega_digital_orders o JOIN omega_digital_offers f USING(connection_id,offer_key) WHERE o.connection_id=$1 AND o.id=$2`
	if lock {
		stmt += " FOR UPDATE OF o"
	}
	var definition []byte
	err := q.QueryRowContext(ctx, stmt, s.connection, id).Scan(&a.id, &a.offerID, &a.buyer, &a.created, &a.session, &a.url, &a.payment, &a.charge, &a.state, &a.refunded, &a.dispute, &a.entitled, &a.verified, &a.downloads, &a.open, &definition)
	if errors.Is(err, sql.ErrNoRows) || (err == nil && buyer != nil && !bytes.Equal(a.buyer, buyer)) {
		return a, ErrMissing
	}
	if err != nil {
		return a, err
	}
	a.offer = new(v1.DigitalOffer)
	if err = proto.Unmarshal(definition, a.offer); err != nil {
		return a, err
	}
	if offerKey(a.offer) != a.offerID {
		return a, ErrConflict
	}
	return a, nil
}

// Start commits intent before the provider call. The caller reuses its order
// id on retry, including after a response was lost. Provider idempotency keys
// are not reused after their guaranteed retention window.
func (s *Shop) Start(ctx context.Context, id string, buyer []byte) (string, error) {
	uid, err := uuid.Parse(id)
	if err != nil || uid == uuid.Nil || uid.String() != id || len(buyer) != 32 {
		return "", ErrMissing
	}
	_, err = s.db.ExecContext(ctx, `INSERT INTO omega_digital_orders(connection_id,id,buyer_hash,offer_key) VALUES($1,$2,$3,$4) ON CONFLICT DO NOTHING`, s.connection, id, buyer, s.offerID)
	if err != nil {
		return "", err
	}
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return "", err
	}
	defer tx.Rollback()
	a, err := s.order(ctx, tx, id, buyer, true)
	if err != nil {
		return "", err
	}
	if a.url != "" {
		if !a.open {
			return s.origin + "/orders/" + id, nil
		}
		return a.url, nil
	}
	if time.Since(a.created) >= 23*time.Hour {
		return "", ErrConflict
	}
	sess, err := s.provider.create(ctx, id, a.offer, s.origin)
	if err != nil {
		return "", err
	}
	_, err = tx.ExecContext(ctx, `UPDATE omega_digital_orders SET session_id=$3,checkout_url=$4,checkout_open=true WHERE connection_id=$1 AND id=$2`, s.connection, id, sess.id, sess.url)
	if err != nil {
		return "", err
	}
	return sess.url, tx.Commit()
}

const subjectMatch = `((i.subject_kind='session' AND i.subject_id=o.session_id) OR (i.subject_kind='payment' AND i.subject_id=o.payment_id) OR (i.subject_kind='charge' AND i.subject_id=o.charge_id) OR (i.subject_kind='order_offer' AND i.subject_id=o.id::text || '/' || o.offer_key))`

func (s *Shop) Record(ctx context.Context, raw []byte, signature string) error {
	e, err := readEvent(raw, signature, s.webhookSecret, time.Now())
	if err != nil {
		return fmt.Errorf("%w: %v", ErrInvalidEvent, err)
	}
	if e.id == "" {
		return nil
	}
	res, err := s.db.ExecContext(ctx, `INSERT INTO omega_digital_inbox AS i(connection_id,id,event_type,subject_kind,subject_id,observed_at)
		VALUES($1,$2,$3,$4,$5,$6) ON CONFLICT(connection_id,id) DO UPDATE SET id=excluded.id
		WHERE (i.event_type,i.subject_kind,i.subject_id,i.observed_at)=(excluded.event_type,excluded.subject_kind,excluded.subject_id,excluded.observed_at)`, s.connection, e.id, e.kind, e.subject, e.ref, e.created)
	if err != nil {
		return err
	}
	n, err := res.RowsAffected()
	if err == nil && n != 1 {
		return ErrConflict
	}
	return err
}

func (a order) checkedFact(ctx context.Context, check func(context.Context, string, string, *v1.DigitalOffer) (fact, error)) (fact, error) {
	if a.session == "" {
		return fact{}, ErrConflict
	}
	f, err := check(ctx, a.id, a.session, a.offer)
	if err != nil {
		return fact{}, err
	}
	if (a.charge != "" && (a.charge != f.charge || a.payment != f.payment)) || f.refunded < a.refunded ||
		(a.entitled.Valid && (f.state == pending || f.state == failed || f.state == expired)) {
		return fact{}, ErrConflict
	}
	// Only an already-verified provider expiration can confirm cancellation.
	if a.state == cancelled && f.state == expired {
		f.state = cancelled
	}
	return f, nil
}

func (s *Shop) syncTx(ctx context.Context, tx *sql.Tx, id string, buyer []byte) (order, error) {
	a, err := s.order(ctx, tx, id, buyer, true)
	if err != nil {
		return a, err
	}
	f, err := a.checkedFact(ctx, s.provider.check)
	if err != nil {
		return a, err
	}
	_, err = tx.ExecContext(ctx, `UPDATE omega_digital_orders SET payment_id=$3,charge_id=$4,payment=$5,refunded=$6,dispute=$7,
		entitled_at=CASE WHEN $5=2 THEN coalesce(entitled_at,now()) ELSE entitled_at END,verified_at=clock_timestamp(),
		checkout_open=$8,next_check=now()+CASE WHEN $5=1 OR $8 THEN interval '1 minute' ELSE interval '6 hours' END WHERE connection_id=$1 AND id=$2`,
		s.connection, id, f.payment, f.charge, int(f.state), f.refunded, f.dispute, f.open)
	if err != nil {
		return a, err
	}
	// Entries received during the provider read are left for the next pass.
	_, err = tx.ExecContext(ctx, `UPDATE omega_digital_inbox i SET order_id=o.id,status='processed' FROM omega_digital_orders o
		WHERE i.connection_id=o.connection_id AND o.connection_id=$1 AND o.id=$2 AND i.status='queued' AND i.received_at<=now() AND `+subjectMatch, s.connection, id)
	if err != nil {
		return a, err
	}
	return s.order(ctx, tx, id, buyer, false)
}

func (s *Shop) Refresh(ctx context.Context, id string, buyer []byte) error {
	if len(buyer) != 32 {
		return ErrMissing
	}
	return s.refresh(ctx, id, buyer)
}

func (s *Shop) refresh(ctx context.Context, id string, buyer []byte) error {
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	if _, err = s.syncTx(ctx, tx, id, buyer); err != nil {
		return err
	}
	return tx.Commit()
}

func (s *Shop) Cancel(ctx context.Context, id string, buyer []byte) error {
	if len(buyer) != 32 {
		return ErrMissing
	}
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	a, err := s.order(ctx, tx, id, buyer, true)
	if err != nil {
		return err
	}
	if a.state == cancelled || a.state == expired {
		return nil
	}
	if a.session == "" || !a.open {
		return ErrConflict
	}
	// The success/cancel browser redirects are read-only. Explicit cancellation
	// expires the provider session and verifies the result before saving.
	if err = s.provider.expire(ctx, a.session); err != nil {
		f, readErr := s.provider.check(ctx, a.id, a.session, a.offer)
		if readErr != nil || f.state != expired {
			return ErrConflict
		}
	}
	a, err = s.syncTx(ctx, tx, id, buyer)
	if err != nil {
		return err
	}
	if a.state != expired {
		return ErrConflict
	}
	_, err = tx.ExecContext(ctx, `UPDATE omega_digital_orders SET payment=$3 WHERE connection_id=$1 AND id=$2`, s.connection, id, int(cancelled))
	if err != nil {
		return err
	}
	return tx.Commit()
}

func eligible(a order, now time.Time) bool {
	return a.state == paid && a.entitled.Valid && now.Before(a.entitled.Time.Add(downloadLifetime))
}

func (s *Shop) Receipt(ctx context.Context, id string, buyer []byte) (*v1.DigitalOrderReceipt, error) {
	if len(buyer) != 32 {
		return nil, ErrMissing
	}
	return s.receipt(ctx, id, buyer)
}

// OperatorReceipt is the server-side reader for a verified sandbox merchant.
// The buyer HTTP handler never exposes this operation. The caller must possess
// both the order database and that merchant's test credential.
func OperatorReceipt(ctx context.Context, db *sql.DB, gateway *StripeTest, business, product, id string) (*v1.DigitalOrderReceipt, error) {
	account, err := gateway.Account(ctx)
	if err != nil {
		return nil, errors.New("Stripe could not verify the sandbox account")
	}
	s := &Shop{db: db, provider: gateway, connection: account + "/" + business}
	return s.currentReceipt(ctx, product, id)
}

func (s *Shop) currentReceipt(ctx context.Context, product, id string) (*v1.DigitalOrderReceipt, error) {
	uid, err := uuid.Parse(id)
	if err != nil || uid.String() != id || product == "" {
		return nil, ErrMissing
	}
	a, err := s.order(ctx, s.db, id, nil, false)
	if err != nil {
		return nil, err
	}
	if a.offer.ProductId != product {
		return nil, ErrMissing
	}
	if err = s.refresh(ctx, id, nil); err != nil {
		return nil, err
	}
	return s.receipt(ctx, id, nil)
}

func (s *Shop) receipt(ctx context.Context, id string, buyer []byte) (*v1.DigitalOrderReceipt, error) {
	tx, err := s.db.BeginTx(ctx, &sql.TxOptions{Isolation: sql.LevelRepeatableRead, ReadOnly: true})
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()
	a, err := s.order(ctx, tx, id, buyer, false)
	if err != nil {
		return nil, err
	}
	r := &v1.DigitalOrderReceipt{
		OrderId: a.id, Offer: a.offer, TestMode: true, Payment: a.state, RefundedMinor: a.refunded,
		DownloadsIssued: a.downloads, ProviderSessionId: a.session, ProviderPaymentId: a.payment, ProviderChargeId: a.charge, DisputeStatus: a.dispute,
		DownloadAvailable: eligible(a, time.Now()), CheckoutOpen: a.open,
	}
	if a.verified.Valid {
		r.VerifiedAt = a.verified.Time.UTC().Format(time.RFC3339Nano)
	}
	if a.entitled.Valid {
		r.EntitlementId = "entitlement-" + a.id
		r.DownloadExpiresAt = a.entitled.Time.Add(downloadLifetime).UTC().Format(time.RFC3339Nano)
	}
	rows, err := tx.QueryContext(ctx, `SELECT i.id,i.event_type,i.status,i.attempts,i.received_at FROM omega_digital_inbox i JOIN omega_digital_orders o
		ON o.connection_id=i.connection_id AND (i.order_id=o.id OR `+subjectMatch+`) WHERE o.connection_id=$1 AND o.id=$2 ORDER BY i.received_at,i.id`, s.connection, id)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		e := new(v1.DigitalOrderEvent)
		var at time.Time
		if err = rows.Scan(&e.ProviderEventId, &e.EventType, &e.ProcessingStatus, &e.Attempts, &at); err != nil {
			return nil, err
		}
		e.ReceivedAt = at.UTC().Format(time.RFC3339Nano)
		r.Events = append(r.Events, e)
		if e.ProcessingStatus != "processed" {
			r.DownloadAvailable = false
		}
	}
	if err = rows.Err(); err != nil {
		return nil, err
	}
	return r, tx.Commit()
}

func (s *Shop) Download(ctx context.Context, id string, buyer []byte) (*v1.DigitalOffer, []byte, error) {
	if len(buyer) != 32 {
		return nil, nil, ErrMissing
	}
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return nil, nil, err
	}
	defer tx.Rollback()
	a, err := s.syncTx(ctx, tx, id, buyer)
	if err != nil {
		return nil, nil, err
	}
	if !eligible(a, time.Now()) {
		if err = tx.Commit(); err != nil {
			return nil, nil, err
		}
		return nil, nil, ErrBlocked
	}
	var blocked bool
	err = tx.QueryRowContext(ctx, `SELECT EXISTS(SELECT 1 FROM omega_digital_inbox i JOIN omega_digital_orders o ON o.connection_id=i.connection_id AND `+subjectMatch+`
		WHERE o.connection_id=$1 AND o.id=$2 AND i.status<>'processed')`, s.connection, id).Scan(&blocked)
	if err != nil {
		return nil, nil, err
	}
	if blocked {
		return nil, nil, ErrBlocked
	}
	var data []byte
	err = tx.QueryRowContext(ctx, `SELECT archive FROM omega_digital_offers WHERE connection_id=$1 AND offer_key=$2`, s.connection, a.offerID).Scan(&data)
	if err != nil {
		return nil, nil, err
	}
	if fingerprint(data) != a.offer.ArchiveSha256 {
		return nil, nil, fmt.Errorf("saved delivery file changed")
	}
	_, err = tx.ExecContext(ctx, `UPDATE omega_digital_orders SET downloads=downloads+1 WHERE connection_id=$1 AND id=$2`, s.connection, id)
	if err != nil {
		return nil, nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, nil, err
	}
	return a.offer, data, nil
}
