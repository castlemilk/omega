package posters

import (
	"archive/zip"
	"bytes"
	"errors"
	"fmt"
	"io"
	"slices"
	"strings"
	"time"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/benebsworth/omega/internal/venture"
	"google.golang.org/protobuf/encoding/protojson"
)

const (
	DeliveryInspector = "omega.delivery-inspector/v1"
	DeliveryTool      = "posters.verify-delivery/v1"
)

// VerifyDelivery is shared by the native runner and the private Studio
// runtime. Its only inputs are bytes from the three named resources.
func VerifyDelivery(r *v1.DeliveryCheckRequest) (*v1.DeliveryCheckEvidence, error) {
	if r == nil || r.BusinessId != StudioBusinessID || r.ProductId != StudioProductID ||
		r.OrderId == "" || r.StatementId == "" || len(r.StatementJson) > 160000 ||
		len(r.EditionPacketJson) > 1<<20 || len(r.BuyerZip) > maxFileSize {
		return nil, errors.New("the order evidence is outside this poster product or its input limits")
	}
	statementSHA, packetSHA, archiveSHA := sourceDigest(r.StatementJson), sourceDigest(r.EditionPacketJson), sourceDigest(r.BuyerZip)
	inputs := []*v1.VentureResourceGrant{
		{Role: "test-order", Id: r.OrderId, Sha256: statementSHA},
		{Role: "statement", Id: r.StatementId, Sha256: statementSHA},
		{Role: "edition", Id: r.ProductId, Sha256: packetSHA},
		{Role: "buyer-zip", Id: r.ProductId, Sha256: archiveSHA},
	}
	if err := venture.CheckRead(r.Mandate, r.Context, DeliveryInspector, DeliveryTool, 2*time.Minute, inputs); err != nil {
		return nil, err
	}
	candidate, err := reviewedCandidate(r.EditionPacketJson, packetSHA)
	if err != nil {
		return nil, errors.New("the issued edition packet differs from the reviewed poster release")
	}
	ref := candidate.GetPrintPack()
	if ref.GetSha256() != archiveSHA || int(ref.GetBytes()) != len(r.BuyerZip) {
		return nil, errors.New("the buyer ZIP does not match the issued edition")
	}
	order, err := verifiedDeliveryOrder(r, candidate.Edition, packetSHA, archiveSHA)
	if err != nil {
		return nil, err
	}
	files, err := checkedDeliveryMembers(r.BuyerZip, candidate.DeliveryFiles)
	if err != nil {
		return nil, err
	}
	return &v1.DeliveryCheckEvidence{
		OrderId: order.OrderId, StatementId: r.StatementId, StatementSha256: statementSHA,
		OrderVerifiedAt: order.VerifiedAt.Value, Edition: candidate.Edition, PacketSha256: packetSHA,
		Archive: &v1.CheckedDeliveryFile{Name: ref.Name, Sha256: archiveSHA, Bytes: ref.Bytes},
		Files:   files, DownloadsIssued: order.DownloadsIssued, TestMode: true,
	}, nil
}

func verifiedDeliveryOrder(r *v1.DeliveryCheckRequest, edition, packet, archive string) (*v1.CommerceStatementOrder, error) {
	var statement v1.CommerceStatement
	if err := protojson.Unmarshal(r.StatementJson, &statement); err != nil || statement.Schema != "omega.commerce-statement/v1" ||
		!statement.TestMode || statement.BusinessId != r.BusinessId || statement.ProductId != r.ProductId {
		return nil, errors.New("the statement is not a test statement for this product")
	}
	var found *v1.CommerceStatementOrder
	for _, order := range statement.Orders {
		if order.GetOrderId() != r.OrderId {
			continue
		}
		if found != nil {
			return nil, errors.New("the order appears more than once in the statement")
		}
		found = order
	}
	if found == nil || found.Edition != edition || found.PacketSha256 != packet || found.ArchiveSha256 != archive ||
		found.DownloadsIssued < 1 || found.UnresolvedEvents != 0 || found.QuotedMinor <= 0 ||
		found.GetCapturedMinor().GetValue() != found.QuotedMinor || found.RefundedMinor == nil ||
		found.RefundedMinor.Value < 0 || found.RefundedMinor.Value > found.QuotedMinor {
		return nil, errors.New("the selected order has no verified download of this edition")
	}
	switch found.Payment {
	case v1.DigitalPaymentState_DIGITAL_PAYMENT_STATE_REFUNDED:
		if found.RefundedMinor.Value != found.QuotedMinor {
			return nil, errors.New("the order's refund differs from the captured amount")
		}
	case v1.DigitalPaymentState_DIGITAL_PAYMENT_STATE_PAID:
		if found.RefundedMinor.Value == found.QuotedMinor {
			return nil, errors.New("the paid order is recorded as fully refunded")
		}
	default:
		return nil, errors.New("the test payment could not be verified")
	}
	observed, e1 := time.Parse(time.RFC3339Nano, found.GetVerifiedAt().GetValue())
	reported, e2 := time.Parse(time.RFC3339Nano, statement.VerifiedAt)
	checked, _ := time.Parse(time.RFC3339Nano, r.Context.CheckedAt)
	if e1 != nil || e2 != nil || observed.After(reported) || reported.After(checked) {
		return nil, errors.New("the order has no valid observation time")
	}
	return found, nil
}

func checkedDeliveryMembers(body []byte, expected []*v1.PosterFile) ([]*v1.CheckedDeliveryFile, error) {
	archive, err := zip.NewReader(bytes.NewReader(body), int64(len(body)))
	if err != nil || len(expected) != 8 || len(archive.File) != len(expected) {
		return nil, errors.New("the buyer ZIP does not contain the complete poster edition")
	}
	remaining := make(map[string]*v1.PosterFile, len(expected))
	for _, ref := range expected {
		if ref.GetName() == "" || remaining[ref.Name] != nil {
			return nil, errors.New("the issued edition contains an invalid or repeated member")
		}
		remaining[ref.Name] = ref
	}
	files := make([]*v1.CheckedDeliveryFile, 0, len(expected))
	for _, member := range archive.File {
		ref := remaining[member.Name]
		if ref == nil || !member.Mode().IsRegular() || member.Flags&1 != 0 || ref.Bytes == 0 ||
			ref.Bytes > maxFileSize || member.UncompressedSize64 != uint64(ref.Bytes) {
			return nil, errors.New("an archive member is missing, repeated or differs from the edition")
		}
		file, err := member.Open()
		if err != nil {
			return nil, errors.New("an archive member could not be opened")
		}
		data, readErr := io.ReadAll(io.LimitReader(file, int64(ref.Bytes)+1))
		closeErr := file.Close()
		if readErr != nil || closeErr != nil || len(data) != int(ref.Bytes) || sourceDigest(data) != ref.Sha256 {
			return nil, fmt.Errorf("%s does not match the reviewed bytes", ref.Name)
		}
		files = append(files, &v1.CheckedDeliveryFile{Name: ref.Name, Sha256: ref.Sha256, Bytes: ref.Bytes})
		delete(remaining, member.Name)
	}
	slices.SortFunc(files, func(a, b *v1.CheckedDeliveryFile) int { return strings.Compare(a.Name, b.Name) })
	return files, nil
}
