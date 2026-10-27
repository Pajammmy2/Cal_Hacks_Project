import Foundation

/// W1's haptic vocabulary: a person who cannot read the screen or hear the phone in a smoky street still gets
/// left / right / straight in their hand. Patterns are data so they can be tested and listed in the help text.
public enum HapticCue: String, CaseIterable, Sendable {
    case left, right, straight, arrived, offRoute, fire, notice

    public enum Strength: Sendable { case light, medium, heavy }
    public struct Pulse: Equatable, Sendable {
        public var strength: Strength
        /// Seconds to wait after this pulse before the next one.
        public var gapS: Double
        public init(_ strength: Strength, gap gapS: Double) { self.strength = strength; self.gapS = gapS }
    }

    public var pulses: [Pulse] {
        switch self {
        case .left:     return [Pulse(.medium, gap: 0.18), Pulse(.medium, gap: 0)]                                 // two taps
        case .right:    return [Pulse(.medium, gap: 0.18), Pulse(.medium, gap: 0.18), Pulse(.medium, gap: 0)]      // three taps
        case .straight: return [Pulse(.heavy, gap: 0.06), Pulse(.heavy, gap: 0.06), Pulse(.heavy, gap: 0)]         // one long buzz
        case .arrived:  return [Pulse(.light, gap: 0.14), Pulse(.medium, gap: 0.14), Pulse(.heavy, gap: 0)]        // rising triple
        case .offRoute: return [Pulse(.heavy, gap: 0.45), Pulse(.heavy, gap: 0)]                                  // buzz, pause, buzz
        case .fire:     return [Pulse(.heavy, gap: 0.10), Pulse(.heavy, gap: 0.10), Pulse(.heavy, gap: 0)]         // heavy triple
        case .notice:   return [Pulse(.medium, gap: 0)]
        }
    }

    /// The pattern for a cue group that just became current: turns by side, continue/start = straight, arrive = arrived.
    public static func forCue(_ cue: Cue) -> HapticCue? {
        switch cue.template {
        case "turn", "turn_slight", "turn_sharp":
            guard case .str(let side)? = cue.vars["side"] else { return nil }
            return side == "left" ? .left : (side == "right" ? .right : nil)
        case "continue", "start": return .straight
        case "arrive": return .arrived
        default: return nil
        }
    }

    /// Spoken once at Start so the vocabulary is learnable (W1 legend).
    public static let legend = "Two taps means left. Three taps means right. One long buzz means straight on."
}
