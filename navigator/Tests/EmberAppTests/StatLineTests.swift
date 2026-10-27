import Foundation
import CoreGraphics
import Testing
@testable import EmberApp
@testable import EmberCore

/// Navigate with "Demo: step through route" on: the stat strip ("270 m to next turn · 36 min to go") plus the demo
/// Next button truncated the caption to "to next…" at the default text size. StatLine's smallest shrink step must
/// make the strip fit a 393 pt phone with the icon-only Next, so the truncating fallback is never reached.
@Suite struct StatLineTests {
    static let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
    static let bold = root.appendingPathComponent("navigator/EmberNavigator/Fonts/Inter-Bold.ttf")
    static let regular = root.appendingPathComponent("navigator/EmberNavigator/Fonts/Inter-Regular.ttf")
    static let card: CGFloat = 393 - 32 - 24          // screen padding 16, card padding 12 (WordFitTests)
    static let compactNext: CGFloat = 44 + 10          // DemoNextButton minWidth + HStack spacing

    /// Width of the default-size strip at `scale`: per item SF icon (~1.3 × small) + 6 + value(big heavy) + 6 + caption(small), 18 between items.
    static func width(_ items: [(String, String)], scale: CGFloat) throws -> CGFloat {
        let big = try #require(WordFit.font(url: bold, size: StatLineMetrics.big * scale))
        let small = try #require(WordFit.font(url: bold, size: StatLineMetrics.small * scale))   // semibold draws Inter-Bold
        var w: CGFloat = 0
        for (i, it) in items.enumerated() {
            if i > 0 { w += 18 }
            w += StatLineMetrics.small * scale * 1.3 + 6 + WordFit.width(it.0, font: big) + 6 + WordFit.width(it.1, font: small)
        }
        return w
    }

    static let longest = [("990 m", "to next turn"), ("99 min", "to go")]

    @Test func smallestShrinkStepFitsNextToTheDemoButton() throws {
        let s = try #require(StatLineMetrics.shrinkSteps.min())
        #expect(StatLineMetrics.shrinkSteps.first == 1 && StatLineMetrics.shrinkSteps == StatLineMetrics.shrinkSteps.sorted(by: >))
        let w = try Self.width(Self.longest, scale: s)
        #expect(w + Self.compactNext <= Self.card, "strip \(Int(w)) pt + Next \(Int(Self.compactNext)) > card \(Int(Self.card)) at ×\(s)")
    }
}
