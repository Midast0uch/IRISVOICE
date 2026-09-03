#include "security_sanitizer.h"
#include <re2/re2.h>
#include <iostream>
#include <algorithm>

// ============================================================================
// SecuritySanitizer — Phase 3 Complete
// Uses Google RE2 for guaranteed linear-time matching (O(n)), eliminating
// all ReDoS risk. No hard cap before scan — full payload is sanitized,
// then truncated to MAX_STORED_BYTES if needed.
//
// Patterns use BOUNDED quantifiers only: [A-Za-z0-9]{16,64}
// Never use unbounded wildcards like .* or .+ with RE2.
// ============================================================================

SecuritySanitizer& SecuritySanitizer::get_instance() {
    static SecuritySanitizer instance;
    return instance;
}

SecuritySanitizer::SecuritySanitizer() {
    // Pattern 1: Generic API keys / tokens / secrets
    // Matches: api_key=..., token: ..., secret = ...
    // Bounded to 16-64 alphanum chars (no .*)
    rules_.push_back({
        new re2::RE2(R"((?i)(api[_-]?key|token|secret)[\s]*[=:][\s]*['"]?[a-zA-Z0-9\-_]{16,64}['"]?)"),
        "[REDACTED:api_key]"
    });

    // Pattern 2: OpenAI API keys (sk-...)
    // sk- followed by exactly 48 alphanum chars
    rules_.push_back({
        new re2::RE2(R"(sk-[a-zA-Z0-9]{48})"),
        "[REDACTED:openai_key]"
    });

    // Pattern 3: SSH private key blocks (RE2 has no backrefs; split by type)
    // RE2 max repetition ~1000; use base64-safe charset + newline.
    rules_.push_back({
        new re2::RE2(R"(-----BEGIN RSA PRIVATE KEY-----[A-Za-z0-9+/=\n]{100,1000}-----END RSA PRIVATE KEY-----)"),
        "[REDACTED:ssh_key]"
    });
    rules_.push_back({
        new re2::RE2(R"(-----BEGIN DSA PRIVATE KEY-----[A-Za-z0-9+/=\n]{100,1000}-----END DSA PRIVATE KEY-----)"),
        "[REDACTED:ssh_key]"
    });
    rules_.push_back({
        new re2::RE2(R"(-----BEGIN EC PRIVATE KEY-----[A-Za-z0-9+/=\n]{100,1000}-----END EC PRIVATE KEY-----)"),
        "[REDACTED:ssh_key]"
    });
    rules_.push_back({
        new re2::RE2(R"(-----BEGIN OPENSSH PRIVATE KEY-----[A-Za-z0-9+/=\n]{100,1000}-----END OPENSSH PRIVATE KEY-----)"),
        "[REDACTED:ssh_key]"
    });

    // Pattern 4: Database connection strings — password field
    // password= followed by 8-64 non-semicolon/non-space chars
    rules_.push_back({
        new re2::RE2(R"((?i)(password)[\s]*=[\s]*[^;\s]{8,64})"),
        "password=[REDACTED]"
    });

    // Pattern 5: AWS access key IDs
    // AKIA followed by exactly 16 uppercase alphanum chars
    rules_.push_back({
        new re2::RE2(R"(AKIA[0-9A-Z]{16})"),
        "[REDACTED:aws_key]"
    });

    // Verify all patterns compiled successfully
    for (const auto& rule : rules_) {
        if (!rule.regex->ok()) {
            std::cerr << "[SecuritySanitizer] FAILED to compile pattern: "
                      << rule.regex->error() << std::endl;
        }
    }
}

SecuritySanitizer::~SecuritySanitizer() {
    for (auto& rule : rules_) {
        delete rule.regex;
    }
}

std::pair<std::string, bool> SecuritySanitizer::sanitize_payload(const std::string& payload) {
    bool modified = false;
    std::string result = payload;

    for (const auto& rule : rules_) {
        if (!rule.regex || !rule.regex->ok()) continue;

        // RE2::GlobalReplace does linear-time matching on the full payload.
        // No ReDoS risk — guaranteed O(n) where n = payload length.
        int replacements = re2::RE2::GlobalReplace(&result, *rule.regex, rule.replacement);
        if (replacements > 0) {
            modified = true;
        }
    }

    // Post-sanitization truncation: bound storage without losing all data.
    // Secrets are already scrubbed from the FULL payload before truncation.
    if (result.size() > MAX_STORED_BYTES) {
        result.resize(MAX_STORED_BYTES);
        result.append("...[TRUNCATED]");
    }

    return {result, modified};
}
