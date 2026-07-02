.PHONY: verify-public verify clean

# Run the full public verification suite
verify-public:
	python scripts/verify.py --report verification-report.ci.json
	python rebuild/test_blob_lookup.py
	python scripts/validate_claims.py

# Alias
verify: verify-public
