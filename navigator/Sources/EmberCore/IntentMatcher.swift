import Foundation

/// The 18 on-device intents (shared/intents.json), in spec order (used as the last tie-break).
public enum Intent: String, CaseIterable, Sendable {
    case blocked, fire, `repeat`, slower, louder, pushing
    case cantMove = "cant_move"
    case whereAmI = "where_am_i"
    case howLong = "how_long"
    case whichWay = "which_way"
    case stop, yes, no
    // Owner additions (demo night): all answered with already-recorded sentences.
    case goHome = "go_home"
    case otherWay = "other"
    case callHelp = "call_help"
    case whereFire = "where_fire"
    case help
}

public struct IntentMatch: Sendable, Equatable {
    public var intent: Intent
    /// The longest synonym that matched.
    public var phrase: String
    /// Number of this intent's synonyms present in the transcript; compared with intents.json "threshold".
    public var confidence: Int
}

/// Keyword matcher: lowercase, word-boundary phrase match, the longest matched phrase wins.
/// Returns nil below the threshold; the caller says "Say again?".
public struct IntentMatcher: Sendable {
    let synonyms: [(Intent, [String])]
    let threshold: Int

    public init(_ file: IntentsFile) {
        synonyms = Intent.allCases.map { i in (i, (file.intents[i.rawValue] ?? []).map(IntentMatcher.normalize)) }
        threshold = file.threshold
    }

    /// Lowercase, curly apostrophes to straight, anything but letters/digits/apostrophes to single spaces.
    public static func normalize(_ s: String) -> String {
        var out = ""
        var space = true
        for ch in s.lowercased() {
            let c: Character = (ch == "\u{2019}" || ch == "\u{2018}" || ch == "`") ? "'" : ch
            if c.isLetter || c.isNumber || c == "'" {
                out.append(c)
                space = false
            } else if !space {
                out.append(" ")
                space = true
            }
        }
        return out.trimmingCharacters(in: .whitespaces)
    }

    public func match(_ transcript: String) -> IntentMatch? {
        let padded = " " + IntentMatcher.normalize(transcript) + " "
        var best: IntentMatch? = nil
        var bestLen = 0
        for (intent, phrases) in synonyms {
            let hits = phrases.filter { !$0.isEmpty && padded.contains(" " + $0 + " ") }
            guard let longest = hits.max(by: { $0.count < $1.count }) else { continue }
            let better: Bool
            if let b = best {
                better = longest.count > bestLen || (longest.count == bestLen && hits.count > b.confidence)
            } else {
                better = true
            }
            if better {
                best = IntentMatch(intent: intent, phrase: longest, confidence: hits.count)
                bestLen = longest.count
            }
        }
        guard let best, best.confidence >= threshold else { return nil }
        return best
    }
}
