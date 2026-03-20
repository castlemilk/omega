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
	os.MkdirAll("/tmp", 0755)
	for _, p := range []string{db.StateDBPath, db.MemoryDBPath} {
		if _, err := os.Stat(p); os.IsNotExist(err) {
			f, _ := os.Create(p)
			if f != nil {
				f.Close()
			}
		}
	}

	database, err := db.New(db.StateDBPath, db.MemoryDBPath)
	if err != nil {
		log.Fatalf("open DB: %v", err)
	}
	defer database.Close()

	h := handler.New(database)
	mux := http.NewServeMux()

	path, svcHandler := omegav1connect.NewOrchestratorServiceHandler(h,
		connect.WithCompressMinBytes(1024),
	)
	mux.Handle(path, svcHandler)

	addr := ":8080"
	log.Printf("Omega API listening on %s", addr)
	log.Fatal(http.ListenAndServe(addr, h2c.NewHandler(withCORS(mux), &http2.Server{})))
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
