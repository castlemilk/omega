package commerce

import (
	"bytes"
	"cmp"
	"encoding/json"
	"errors"
	"fmt"
	"math/big"
	"os"
	"slices"
	"strings"
	"time"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
	bolt "go.etcd.io/bbolt"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"
)

const MaxCostEvidenceBytes = 8 << 20

var (
	receiptBucket    = []byte("production-cost/v1/receipts")
	sourceBucket     = []byte("production-cost/v1/evidence")
	headBucket       = []byte("production-cost/v1/current")
	rootBucket       = []byte("production-cost/v1/original")
	recordedBucket   = []byte("production-cost/v1/recorded-at")
	bookSchemaBucket = []byte("production-cost")
)

type ProductionCostBook struct{ db *bolt.DB }

// The caller supplies the file opener so its local ownership and permissions
// policy is enforced on the descriptor that bbolt actually locks.
func OpenProductionCostBook(path string, readOnly bool, openFile func(string, int, os.FileMode) (*os.File, error)) (*ProductionCostBook, error) {
	if openFile == nil {
		return nil, errors.New("a private cost-book file opener is required")
	}
	db, err := bolt.Open(path, 0600, &bolt.Options{Timeout: 5 * time.Second, ReadOnly: readOnly, OpenFile: openFile})
	if err != nil {
		return nil, fmt.Errorf("open production cost book: %w", err)
	}
	checkSchema := func(tx *bolt.Tx) error {
		if b := tx.Bucket(bookSchemaBucket); b != nil && string(b.Get([]byte("schema"))) == "omega.production-cost-book/v1" {
			return nil
		}
		if first, _ := tx.Cursor().First(); first != nil || !tx.Writable() {
			return errors.New("the selected file is not an Omega production cost book")
		}
		b, err := tx.CreateBucket(bookSchemaBucket)
		if err != nil {
			return err
		}
		return b.Put([]byte("schema"), []byte("omega.production-cost-book/v1"))
	}
	if readOnly {
		err = db.View(checkSchema)
	} else {
		err = db.Update(checkSchema)
	}
	if err != nil {
		_ = db.Close()
		return nil, err
	}
	return &ProductionCostBook{db}, nil
}

func (book *ProductionCostBook) Close() error { return book.db.Close() }

func costSourceKey(r *v1.ProductionCostReceipt) []byte {
	mode := "observed"
	if r.GetSimulated() {
		mode = "simulated"
	}
	return []byte(strings.Join([]string{mode, r.Provider, r.Account, r.LineId}, "\x00"))
}

// Canonical source JSON and its supporting bytes are kept together. The head
// moves only from the expected predecessor. Replaying an already accepted
// revision returns its original digest without moving the head backwards.
func (book *ProductionCostBook) Record(r *v1.ProductionCostReceipt, evidence []byte) (string, error) {
	return book.record(r, evidence, false)
}

// Observe records an unpriced operation once. A retry on another day recovers
// the original observation, including after a subsequent bill or correction.
func (book *ProductionCostBook) Observe(r *v1.ProductionCostReceipt, evidence []byte) (string, error) {
	if r.GetStage() != costProvisional || r.PreviousReceiptSha256 != "" {
		return "", errors.New("an operation observation must be an original provisional receipt")
	}
	return book.record(r, evidence, true)
}

func (book *ProductionCostBook) record(r *v1.ProductionCostReceipt, evidence []byte, observation bool) (string, error) {
	var digest string
	err := book.db.Update(func(tx *bolt.Tx) error {
		var saveErr error
		digest, saveErr = saveCostReceipt(tx, r, evidence, observation)
		return saveErr
	})
	if err != nil {
		return "", err
	}
	return digest, nil
}

func saveCostReceipt(tx *bolt.Tx, r *v1.ProductionCostReceipt, evidence []byte, observation bool) (string, error) {
	if err := validateCostReceipt(r); err != nil {
		return "", err
	}
	if len(evidence) == 0 || len(evidence) > MaxCostEvidenceBytes || fingerprint(evidence) != r.EvidenceSha256 {
		return "", errors.New("the supplied evidence bytes must match the receipt SHA-256 and fit within 8 MiB")
	}
	r = proto.CloneOf(r)
	slices.SortFunc(r.Targets, func(a, b *v1.ProductionCostTarget) int { return cmp.Compare(costTargetKey(a), costTargetKey(b)) })
	encoded, err := protojson.Marshal(r)
	if err != nil {
		return "", err
	}
	var canonical bytes.Buffer
	if err := json.Compact(&canonical, encoded); err != nil {
		return "", err
	}
	raw := canonical.Bytes()
	digest := fingerprint(raw)
	receipts, err := tx.CreateBucketIfNotExists(receiptBucket)
	if err != nil {
		return "", err
	}
	sources, err := tx.CreateBucketIfNotExists(sourceBucket)
	if err != nil {
		return "", err
	}
	heads, err := tx.CreateBucketIfNotExists(headBucket)
	if err != nil {
		return "", err
	}
	roots, err := tx.CreateBucketIfNotExists(rootBucket)
	if err != nil {
		return "", err
	}
	identity := costSourceKey(r)
	if first := roots.Get(identity); observation && first != nil {
		original := new(v1.ProductionCostReceipt)
		originalBytes := receipts.Get(first)
		if fingerprint(originalBytes) != string(first) {
			return "", errors.New("original cost receipt is missing or damaged")
		}
		if err := protojson.Unmarshal(originalBytes, original); err != nil {
			return "", err
		}
		r.ServiceDate = original.ServiceDate
		if !proto.Equal(original, r) || !bytes.Equal(sources.Get([]byte(r.EvidenceSha256)), evidence) {
			return "", errors.New("this run ID already identifies a different observation")
		}
		return string(first), nil
	}
	key := []byte(digest)
	if saved := receipts.Get(key); saved != nil {
		if !bytes.Equal(saved, raw) || !bytes.Equal(sources.Get([]byte(r.EvidenceSha256)), evidence) {
			return "", errors.New("the saved receipt or supporting evidence differs from its digest")
		}
		return digest, nil
	}
	current := string(heads.Get(identity))
	if current != r.PreviousReceiptSha256 {
		return "", fmt.Errorf("this source line has a different current receipt (current %q)", current)
	}
	if existing := sources.Get([]byte(r.EvidenceSha256)); existing == nil {
		if err := sources.Put([]byte(r.EvidenceSha256), evidence); err != nil {
			return "", err
		}
	} else if !bytes.Equal(existing, evidence) {
		return "", errors.New("the saved supporting evidence differs from its digest")
	}
	if err := receipts.Put(key, raw); err != nil {
		return "", err
	}
	recorded, err := tx.CreateBucketIfNotExists(recordedBucket)
	if err != nil {
		return "", err
	}
	if err := recorded.Put(key, []byte(time.Now().UTC().Format(time.RFC3339Nano))); err != nil {
		return "", err
	}
	if current == "" {
		if err := roots.Put(identity, key); err != nil {
			return "", err
		}
	}
	if err := heads.Put(identity, key); err != nil {
		return "", err
	}
	return digest, nil
}

// Export returns exact bytes. source selects the supporting document instead
// of the canonical receipt. A missing or damaged document is an error.
func (book *ProductionCostBook) Export(digest string, source bool) ([]byte, error) {
	if !costDigest.MatchString(digest) {
		return nil, errors.New("expected a lowercase SHA-256 digest")
	}
	bucket := receiptBucket
	if source {
		bucket = sourceBucket
	}
	var result []byte
	err := book.db.View(func(tx *bolt.Tx) error {
		b := tx.Bucket(bucket)
		if b == nil {
			return os.ErrNotExist
		}
		raw := b.Get([]byte(digest))
		if raw == nil {
			return os.ErrNotExist
		}
		if fingerprint(raw) != digest {
			return errors.New("stored cost document differs from its SHA-256")
		}
		result = bytes.Clone(raw)
		return nil
	})
	return result, err
}

func costProductItem(r *v1.ProductionCostReceipt, digest, business, product string) *v1.ProductionCostItem {
	item := &v1.ProductionCostItem{ReceiptSha256: digest, EvidenceSha256: r.EvidenceSha256, PreviousReceiptSha256: r.PreviousReceiptSha256,
		Provider: r.Provider, LineId: r.LineId, ServiceDate: r.ServiceDate, Category: r.Category, Stage: r.Stage, Description: r.Description,
		AllocationBasis: r.AllocationBasis, Currency: r.Currency, SourceTargetCount: uint32(len(r.Targets)), SourceObservedAt: r.SourceObservedAt}
	var amounts []int64
	if r.AmountMicros != nil {
		amounts = costShares(*r.AmountMicros, r.Targets)
	}
	var productAmount int64
	for i, t := range r.Targets {
		if t.BusinessId != business || t.ProductId != product {
			continue
		}
		allocation := &v1.ProductionCostAllocation{Target: t}
		if amounts != nil {
			allocation.AmountMicros = proto.Int64(amounts[i])
			productAmount += amounts[i]
		}
		item.Allocations = append(item.Allocations, allocation)
	}
	if len(item.Allocations) == 0 {
		return nil
	}
	if amounts != nil {
		item.ProductMicros = &productAmount
	}
	return item
}

func (book *ProductionCostBook) Statement(business, product, month string, simulated bool) (*v1.ProductionCostStatement, error) {
	if _, err := time.Parse("2006-01", month); err != nil || len(month) != 7 || !costID.MatchString(business) || !costID.MatchString(product) {
		return nil, errors.New("a product, business and UTC service month (YYYY-MM) are required")
	}
	out := &v1.ProductionCostStatement{Schema: "omega.production-cost-statement/v1", BusinessId: business, ProductId: product, Month: month, Simulated: simulated}
	type group struct {
		currency string
		stage    v1.ProductionCostStage
	}
	type subtotal struct {
		count  uint32
		amount big.Int
	}
	totals := map[group]*subtotal{}
	err := book.db.View(func(tx *bolt.Tx) error {
		heads := tx.Bucket(headBucket)
		if heads == nil {
			return nil
		}
		receipts, recorded := tx.Bucket(receiptBucket), tx.Bucket(recordedBucket)
		if receipts == nil || recorded == nil {
			return errors.New("cost receipt storage is missing")
		}
		return heads.ForEach(func(key, digest []byte) error {
			raw := receipts.Get(digest)
			if raw == nil || fingerprint(raw) != string(digest) {
				return errors.New("current cost receipt is missing or differs from its digest")
			}
			r := new(v1.ProductionCostReceipt)
			if err := protojson.Unmarshal(raw, r); err != nil {
				return err
			}
			if err := validateCostReceipt(r); err != nil {
				return err
			}
			if !bytes.Equal(costSourceKey(r), key) {
				return errors.New("receipt does not belong to its source line")
			}
			if r.GetSimulated() != simulated || !strings.HasPrefix(r.ServiceDate, month+"-") {
				return nil
			}
			item := costProductItem(r, string(digest), business, product)
			if item == nil {
				return nil
			}
			item.RecordedAt = string(recorded.Get(digest))
			if _, err := time.Parse(time.RFC3339Nano, item.RecordedAt); err != nil {
				return errors.New("the cost receipt is missing its acceptance time")
			}
			out.Items = append(out.Items, item)
			if r.Stage == costProvisional {
				out.ProvisionalItems++
			}
			if item.ProductMicros != nil {
				k := group{r.Currency, r.Stage}
				if totals[k] == nil {
					totals[k] = new(subtotal)
				}
				sum := totals[k]
				sum.count++
				sum.amount.Add(&sum.amount, big.NewInt(*item.ProductMicros))
			}
			return nil
		})
	})
	if err != nil {
		return nil, err
	}
	slices.SortFunc(out.Items, func(a, b *v1.ProductionCostItem) int {
		if date := cmp.Compare(a.ServiceDate, b.ServiceDate); date != 0 {
			return date
		}
		return cmp.Compare(a.ReceiptSha256, b.ReceiptSha256)
	})
	for k, total := range totals {
		out.Subtotals = append(out.Subtotals, &v1.ProductionCostSubtotal{Currency: k.currency, Stage: k.stage, Items: total.count, AmountMicros: total.amount.String()})
	}
	slices.SortFunc(out.Subtotals, func(a, b *v1.ProductionCostSubtotal) int {
		if currency := cmp.Compare(a.Currency, b.Currency); currency != 0 {
			return currency
		}
		return cmp.Compare(a.Stage, b.Stage)
	})
	return out, nil
}
