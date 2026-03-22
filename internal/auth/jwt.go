package auth

import (
	"crypto/rsa"
	"errors"
	"fmt"
	"os"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

// Claims holds the validated claims extracted from a JWT.
type Claims struct {
	Subject   string
	Roles     []string
	ExpiresAt time.Time
}

// Validator validates JWT tokens using either HS256 (shared secret) or RS256 (public key).
type Validator struct {
	algorithm string // "HS256" or "RS256"
	secret    []byte // HS256 secret
	publicKey *rsa.PublicKey
	issuer    string
}

// omegaClaims is the internal jwt.Claims implementation used during parsing.
type omegaClaims struct {
	Roles []string `json:"roles,omitempty"`
	jwt.RegisteredClaims
}

// NewValidator reads OMEGA_JWT_SECRET (HS256) or OMEGA_JWT_PUBLIC_KEY (RS256 PEM) env vars.
// If OMEGA_AUTH_ENABLED=true and neither is set, an error is returned.
func NewValidator() (*Validator, error) {
	authEnabled := os.Getenv("OMEGA_AUTH_ENABLED") == "true"
	issuer := os.Getenv("OMEGA_JWT_ISSUER")

	secret := os.Getenv("OMEGA_JWT_SECRET")
	pubKeyPEM := os.Getenv("OMEGA_JWT_PUBLIC_KEY")

	if secret != "" {
		return &Validator{
			algorithm: "HS256",
			secret:    []byte(secret),
			issuer:    issuer,
		}, nil
	}

	if pubKeyPEM != "" {
		pubKey, err := jwt.ParseRSAPublicKeyFromPEM([]byte(pubKeyPEM))
		if err != nil {
			return nil, fmt.Errorf("auth: invalid OMEGA_JWT_PUBLIC_KEY: %w", err)
		}
		return &Validator{
			algorithm: "RS256",
			publicKey: pubKey,
			issuer:    issuer,
		}, nil
	}

	if authEnabled {
		return nil, errors.New("auth: OMEGA_AUTH_ENABLED=true but neither OMEGA_JWT_SECRET nor OMEGA_JWT_PUBLIC_KEY is set")
	}

	// Auth disabled and no keys set — return a no-op validator.
	return &Validator{
		algorithm: "none",
		issuer:    issuer,
	}, nil
}

// ValidateToken parses and validates a JWT string.
// It checks signature, expiry, and optionally the issuer.
func (v *Validator) ValidateToken(tokenStr string) (*Claims, error) {
	if v.algorithm == "none" {
		return nil, errors.New("auth: no JWT secret configured")
	}

	var keyFunc jwt.Keyfunc
	switch v.algorithm {
	case "HS256":
		keyFunc = func(t *jwt.Token) (interface{}, error) {
			if _, ok := t.Method.(*jwt.SigningMethodHMAC); !ok {
				return nil, fmt.Errorf("auth: unexpected signing method: %v", t.Header["alg"])
			}
			return v.secret, nil
		}
	case "RS256":
		keyFunc = func(t *jwt.Token) (interface{}, error) {
			if _, ok := t.Method.(*jwt.SigningMethodRSA); !ok {
				return nil, fmt.Errorf("auth: unexpected signing method: %v", t.Header["alg"])
			}
			return v.publicKey, nil
		}
	default:
		return nil, fmt.Errorf("auth: unsupported algorithm: %s", v.algorithm)
	}

	parserOpts := []jwt.ParserOption{
		jwt.WithExpirationRequired(),
	}
	if v.issuer != "" {
		parserOpts = append(parserOpts, jwt.WithIssuer(v.issuer))
	}

	parsed := &omegaClaims{}
	token, err := jwt.ParseWithClaims(tokenStr, parsed, keyFunc, parserOpts...)
	if err != nil {
		return nil, fmt.Errorf("auth: token validation failed: %w", err)
	}
	if !token.Valid {
		return nil, errors.New("auth: token is not valid")
	}

	expiry, err := parsed.GetExpirationTime()
	if err != nil || expiry == nil {
		return nil, errors.New("auth: token missing expiration")
	}

	subject, err := parsed.GetSubject()
	if err != nil {
		return nil, fmt.Errorf("auth: token missing subject: %w", err)
	}

	return &Claims{
		Subject:   subject,
		Roles:     parsed.Roles,
		ExpiresAt: expiry.Time,
	}, nil
}

// IssueToken creates and signs a new JWT using the HS256 shared secret.
// Returns an error if the validator is not configured for HS256.
func (v *Validator) IssueToken(subject string, roles []string, ttl time.Duration) (string, error) {
	if v.algorithm != "HS256" {
		return "", errors.New("auth: IssueToken requires HS256 (OMEGA_JWT_SECRET)")
	}

	now := time.Now()
	claims := &omegaClaims{
		Roles: roles,
		RegisteredClaims: jwt.RegisteredClaims{
			Subject:   subject,
			IssuedAt:  jwt.NewNumericDate(now),
			ExpiresAt: jwt.NewNumericDate(now.Add(ttl)),
		},
	}
	if v.issuer != "" {
		claims.Issuer = v.issuer
	}

	token := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	signed, err := token.SignedString(v.secret)
	if err != nil {
		return "", fmt.Errorf("auth: failed to sign token: %w", err)
	}
	return signed, nil
}
