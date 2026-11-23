//go:build wasip1

// The private Studio Worker instantiates this reactor once per run with no
// environment, files or network. The ABI exchanges one bounded protobuf.
package main

import (
	"unsafe"

	v1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/benebsworth/omega/projects/posters"
	"google.golang.org/protobuf/proto"
)

var input, output []byte

func main() {}

//go:wasmexport reserve
func reserve(size uint32) uint32 {
	if size == 0 || size > 4<<20 {
		return 0
	}
	input = make([]byte, size)
	return uint32(uintptr(unsafe.Pointer(unsafe.SliceData(input))))
}

//go:wasmexport verify
func verify() uint32 {
	result := new(v1.DeliveryCheckResult)
	request := new(v1.DeliveryCheckRequest)
	if err := proto.Unmarshal(input, request); err != nil {
		result.Outcome = &v1.DeliveryCheckResult_Failure{Failure: "The task request could not be read."}
	} else if evidence, err := posters.VerifyDelivery(request); err != nil {
		result.Outcome = &v1.DeliveryCheckResult_Failure{Failure: err.Error()}
	} else {
		result.Outcome = &v1.DeliveryCheckResult_Evidence{Evidence: evidence}
	}
	input = nil
	output, _ = proto.Marshal(result)
	return uint32(uintptr(unsafe.Pointer(unsafe.SliceData(output))))
}

//go:wasmexport resultSize
func resultSize() uint32 {
	return uint32(len(output))
}
