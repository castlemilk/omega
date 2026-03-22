package middleware

import "context"

// NextFunc is the continuation function passed to each middleware.
// Calling it invokes the next middleware (or the final handler) in the chain.
type NextFunc func(context.Context, *ExecutionRequest) (*ExecutionResponse, error)

// Middleware is implemented by any type that can intercept an execution.
type Middleware interface {
	Process(ctx context.Context, req *ExecutionRequest, next NextFunc) (*ExecutionResponse, error)
}

// FinalHandler is the terminal handler invoked after all middleware.
type FinalHandler func(ctx context.Context, req *ExecutionRequest) (*ExecutionResponse, error)

// Chain holds an ordered list of middleware and a final handler.
// Middleware is applied outermost-first: index 0 runs first on the way in
// and last on the way out.
type Chain struct {
	middlewares []Middleware
	final       FinalHandler
}

// NewChain constructs a Chain with the given final handler and middleware.
// The first middleware in the variadic list is the outermost wrapper.
func NewChain(final FinalHandler, middlewares ...Middleware) *Chain {
	mws := make([]Middleware, len(middlewares))
	copy(mws, middlewares)
	return &Chain{middlewares: mws, final: final}
}

// Execute builds the middleware chain and runs the request through it.
func (c *Chain) Execute(ctx context.Context, req *ExecutionRequest) (*ExecutionResponse, error) {
	return c.build(0)(ctx, req)
}

// build recursively constructs the NextFunc chain starting at index i.
func (c *Chain) build(i int) NextFunc {
	if i >= len(c.middlewares) {
		return NextFunc(c.final)
	}
	mw := c.middlewares[i]
	next := c.build(i + 1)
	return func(ctx context.Context, req *ExecutionRequest) (*ExecutionResponse, error) {
		return mw.Process(ctx, req, next)
	}
}
