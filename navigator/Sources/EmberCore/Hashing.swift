import Foundation
import CryptoKit

/// Audio clip keys (CONTRACTS.md "Audio hashing"); identical to engine/ember_engine/core/hashing.py.
public enum Hashing {
    /// Trim, collapse runs of whitespace to one space (Python str.strip + re `\s+`).
    public static func normalize(_ text: String) -> String {
        let scalars = Array(text.unicodeScalars)
        var lo = 0, hi = scalars.count
        while lo < hi, Py.isSpace(scalars[lo]) { lo += 1 }
        while hi > lo, Py.isSpace(scalars[hi - 1]) { hi -= 1 }
        var out = String.UnicodeScalarView()
        var inSpace = false
        for s in scalars[lo..<hi] {
            if Py.isSpace(s) {
                if !inSpace { out.append(" ") }
                inSpace = true
            } else {
                out.append(s)
                inSpace = false
            }
        }
        return String(out)
    }

    public static func sha1Hex(_ s: String) -> String {
        Insecure.SHA1.hash(data: Data(s.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    public static func clipKey(_ text: String) -> String { sha1Hex(normalize(text)) }

    /// Pronunciation map (whole words only), longest source first; only the text sent to Cartesia changes.
    public static func forCartesia(_ text: String, pronunciation: [(String, String)]) -> String {
        var out = normalize(text)
        let ordered = pronunciation.enumerated().sorted {
            let l0 = $0.element.0.unicodeScalars.count, l1 = $1.element.0.unicodeScalars.count
            return l0 != l1 ? l0 > l1 : $0.offset < $1.offset
        }
        for (_, (src, dst)) in ordered where src != dst {
            let pattern = "\\b" + NSRegularExpression.escapedPattern(for: src) + "\\b"
            guard let re = try? NSRegularExpression(pattern: pattern) else { continue }
            out = re.stringByReplacingMatches(in: out, range: NSRange(out.startIndex..., in: out),
                                              withTemplate: NSRegularExpression.escapedTemplate(for: dst))
        }
        return out
    }
}
