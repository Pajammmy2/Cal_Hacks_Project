import Foundation

/// A second tap of a nervous double tap lands on whatever the NEW screen draws under the finger: on the Simulator a
/// double tap on Choose "Go" put Margaret into the shelter script, because Navigate's "Can't move" sits where "Go"
/// was (at AX5 and at the default size alike). Taps that arrive within `settleS` of a screen change are ignored by the
/// buttons that change the route or the screen; a deliberate tap is never that fast after the screen has changed.
public enum TapGuard {
    public static let settleS: TimeInterval = 0.5

    public static func accepts(tapAt tap: Date, screenShownAt shown: Date) -> Bool {
        tap.timeIntervalSince(shown) >= settleS
    }
}
