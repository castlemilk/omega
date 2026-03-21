package main

import (
	"log"
	"net/http"
	"os"

	"connectrpc.com/connect"
	"golang.org/x/net/http2"
	"golang.org/x/net/http2/h2c"

	omegav1connect "github.com/benebsworth/omega/gen/go/omega/v1/omegav1connect"
	"github.com/benebsworth/omega/internal/db"
	"github.com/benebsworth/omega/internal/handler"
)

func main() {
	// Ensure DB files exist (Python orchestrator creates them on first run)
	stateDBPath := db.StateDBPath()
	memoryDBPath := db.MemoryDBPath()
	_ = os.MkdirAll("/tmp", 0755) //nolint:errcheck,gosec
	for _, p := range []string{stateDBPath, memoryDBPath} {
		if _, err := os.Stat(p); os.IsNotExist(err) {
			f, _ := os.Create(p) //nolint:gosec
			if f != nil {
				f.Close() //nolint:errcheck,gosec
			}
		}
	}

	database, err := db.New(stateDBPath, memoryDBPath)
	if err != nil {
		log.Fatalf("open DB: %v", err)
	}

	vectoraDBPath := db.VectoraDBPath()
	if _, err := os.Stat(vectoraDBPath); os.IsNotExist(err) {
		f, _ := os.Create(vectoraDBPath) //nolint:gosec
		if f != nil {
			f.Close() //nolint:errcheck,gosec
		}
	}
	vdb, err := db.NewVectora(vectoraDBPath)
	if err != nil {
		database.Close() //nolint:errcheck,gosec
		log.Fatalf("open Vectora DB: %v", err)
	}
	defer database.Close()
	defer vdb.Close()

	h := handler.New(database)
	vh := handler.NewVectora(vdb)
	sh := handler.NewState(database)
	mux := http.NewServeMux()

	path, svcHandler := omegav1connect.NewOrchestratorServiceHandler(h,
		connect.WithCompressMinBytes(1024),
	)
	mux.Handle(path, svcHandler)

	vPath, vSvcHandler := omegav1connect.NewVectoraServiceHandler(vh,
		connect.WithCompressMinBytes(1024),
	)
	mux.Handle(vPath, vSvcHandler)

	sPath, sSvcHandler := omegav1connect.NewStateServiceHandler(sh,
		connect.WithCompressMinBytes(1024),
	)
	mux.Handle(sPath, sSvcHandler)

	addr := ":8080"
	log.Printf("Omega API listening on %s", addr)
	log.Fatal(http.ListenAndServe(addr, h2c.NewHandler(withCORS(mux), &http2.Server{}))) //nolint:gosec,gocritic
}

func withCORS(h http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers",
			"Content-Type, Connect-Protocol-Version, Connect-Timeout-Ms, "+
				"Grpc-Timeout, X-Grpc-Web, X-User-Agent, "+
				"connect-accept-encoding, connect-content-encoding")
		w.Header().Set("Access-Control-Expose-Headers",
			"Grpc-Status, Grpc-Message, Grpc-Status-Details-Bin, "+
				"connect-accept-encoding, connect-content-encoding")
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		h.ServeHTTP(w, r)
	})
}
