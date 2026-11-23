package posters

import (
	"fmt"
	"os"
	"path/filepath"
	"testing"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/wrapperspb"
)

// The release Mac supplies the actual issued archives shared with Studio.
// The pure contract tests below run even on checkouts without those assets.
func TestVerifyIssuedDelivery(t *testing.T) {
	root := os.Getenv("OMEGA_POSTER_TEST_COLLECTION")
	if root == "" {
		t.Skip("set OMEGA_POSTER_TEST_COLLECTION to the Studio collection to qualify issued files")
	}
	for _, edition := range []string{OriginalEdition, EditorialEdition} {
		t.Run(edition, func(t *testing.T) {
			packet, err := os.ReadFile(filepath.Join("testdata", edition+".json"))
			require.NoError(t, err)
			candidate, err := reviewedCandidate(packet, sourceDigest(packet))
			require.NoError(t, err)
			archive, err := os.ReadFile(filepath.Join(root, candidate.PrintPack.Name))
			require.NoError(t, err)
			const now = "2026-11-23T00:00:00Z"
			statement := &v1.CommerceStatement{Schema: "omega.commerce-statement/v1", TestMode: true, BusinessId: StudioBusinessID,
				ProductId: StudioProductID, VerifiedAt: now, Orders: []*v1.CommerceStatementOrder{{
					OrderId: "test-order", Edition: edition, PacketSha256: sourceDigest(packet), ArchiveSha256: candidate.PrintPack.Sha256,
					Payment: v1.DigitalPaymentState_DIGITAL_PAYMENT_STATE_REFUNDED, DownloadsIssued: 1, VerifiedAt: wrapperspb.String(now),
					QuotedMinor: 1200, CapturedMinor: wrapperspb.Int64(1200), RefundedMinor: wrapperspb.Int64(1200),
				}}}
			report := testLaunchWire(t, statement)
			r := &v1.DeliveryCheckRequest{BusinessId: StudioBusinessID, ProductId: StudioProductID, OrderId: "test-order", StatementId: "statement",
				Context: &v1.VentureTaskContext{TenantId: "tenant", VentureId: "venture", VentureRevision: 1, AuthorizingActor: "owner", CheckedAt: now},
				Mandate: &v1.VentureTaskMandate{RunId: "check", TenantId: "tenant", VentureId: "venture", VentureRevision: 1, AuthorizingActor: "owner",
					Principal: DeliveryInspector, Objective: "Check the issued download", Tools: []string{DeliveryTool}, MaxTasks: 1,
					EffectPolicy: v1.VentureEffectPolicy_VENTURE_EFFECT_POLICY_READ_ONLY, IssuedAt: now, ExpiresAt: "2026-11-23T00:02:00Z",
					Resources: []*v1.VentureResourceGrant{{Role: "test-order", Id: "test-order", Sha256: sourceDigest(report)},
						{Role: "statement", Id: "statement", Sha256: sourceDigest(report)},
						{Role: "edition", Id: StudioProductID, Sha256: sourceDigest(packet)},
						{Role: "buyer-zip", Id: StudioProductID, Sha256: candidate.PrintPack.Sha256}}},
				StatementJson: report, EditionPacketJson: packet, BuyerZip: archive}
			result, err := VerifyDelivery(r)
			require.NoError(t, err)
			require.Len(t, result.Files, 8)
			require.Equal(t, candidate.PrintPack.Sha256, result.Archive.Sha256)
			require.Equal(t, now, result.OrderVerifiedAt)
			r.BuyerZip[len(archive)/2] ^= 1
			_, err = VerifyDelivery(r)
			require.Error(t, err)
		})
	}
}

func TestDeliveryMembers(t *testing.T) {
	files := map[string][]byte{}
	var expected []*v1.PosterFile
	for i := 0; i < 8; i++ {
		name := fmt.Sprintf("member-%d", i)
		body := []byte("issued " + name)
		files[name] = body
		expected = append(expected, &v1.PosterFile{Name: name, Bytes: uint32(len(body)), Sha256: sourceDigest(body)})
	}
	zip := sellerTestZip(t, files, "")
	checked, err := checkedDeliveryMembers(zip, expected)
	require.NoError(t, err)
	for i, file := range checked {
		require.Equal(t, expected[i].Name, file.Name)
		require.Equal(t, expected[i].Sha256, file.Sha256)
	}
	files["member-0"][0] ^= 1
	_, err = checkedDeliveryMembers(sellerTestZip(t, files, ""), expected)
	require.Error(t, err)
	delete(files, "member-0")
	_, err = checkedDeliveryMembers(sellerTestZip(t, files, "member-1"), expected)
	require.Error(t, err)
	_, err = checkedDeliveryMembers(zip[:len(zip)-12], expected)
	require.Error(t, err)
}

func TestDeliveryRequiresObservedPaymentAndIssuedDownload(t *testing.T) {
	const observed = "2026-11-23T00:00:00Z"
	base := &v1.CommerceStatement{Schema: "omega.commerce-statement/v1", BusinessId: StudioBusinessID,
		ProductId: StudioProductID, TestMode: true, VerifiedAt: observed, Orders: []*v1.CommerceStatementOrder{{
			OrderId: "selected", Edition: EditorialEdition, PacketSha256: editorialPacketSHA, ArchiveSha256: "archive",
			QuotedMinor: 1200, CapturedMinor: wrapperspb.Int64(1200), RefundedMinor: wrapperspb.Int64(0),
			Payment: v1.DigitalPaymentState_DIGITAL_PAYMENT_STATE_PAID, VerifiedAt: wrapperspb.String(observed), DownloadsIssued: 1,
		}}}
	read := func(s *v1.CommerceStatement) error {
		r := &v1.DeliveryCheckRequest{BusinessId: StudioBusinessID, ProductId: StudioProductID, OrderId: "selected",
			Context: &v1.VentureTaskContext{CheckedAt: observed}, StatementJson: testLaunchWire(t, s)}
		_, err := verifiedDeliveryOrder(r, EditorialEdition, editorialPacketSHA, "archive")
		return err
	}
	require.NoError(t, read(base))
	refunded := proto.CloneOf(base)
	refunded.Orders[0].Payment = v1.DigitalPaymentState_DIGITAL_PAYMENT_STATE_REFUNDED
	refunded.Orders[0].RefundedMinor.Value = 1200
	require.NoError(t, read(refunded))
	for name, mutate := range map[string]func(*v1.CommerceStatement){
		"live":               func(s *v1.CommerceStatement) { s.TestMode = false },
		"other business":     func(s *v1.CommerceStatement) { s.BusinessId = "other" },
		"other item":         func(s *v1.CommerceStatement) { s.ProductId = "other" },
		"ambiguous order":    func(s *v1.CommerceStatement) { s.Orders = append(s.Orders, s.Orders[0]) },
		"missing order":      func(s *v1.CommerceStatement) { s.Orders = nil },
		"unverified":         func(s *v1.CommerceStatement) { s.Orders[0].VerifiedAt = nil },
		"future observation": func(s *v1.CommerceStatement) { s.VerifiedAt = "2026-11-23T01:00:00Z" },
		"uncaptured":         func(s *v1.CommerceStatement) { s.Orders[0].CapturedMinor = nil },
		"wrong refund":       func(s *v1.CommerceStatement) { s.Orders[0].RefundedMinor.Value = 1200 },
		"unresolved":         func(s *v1.CommerceStatement) { s.Orders[0].UnresolvedEvents = 1 },
		"no download":        func(s *v1.CommerceStatement) { s.Orders[0].DownloadsIssued = 0 },
		"other release":      func(s *v1.CommerceStatement) { s.Orders[0].PacketSha256 = originalPacketSHA },
		"other archive":      func(s *v1.CommerceStatement) { s.Orders[0].ArchiveSha256 = "other" },
	} {
		t.Run(name, func(t *testing.T) {
			statement := proto.CloneOf(base)
			mutate(statement)
			require.Error(t, read(statement))
		})
	}
}
