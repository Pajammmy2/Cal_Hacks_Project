import Testing
import Foundation
import CoreGraphics
@testable import EmberCore

/// Owner rule #4 on EVERY screen (pass 3: "Margar / et" on Home): for each text element the app draws, the widest word
/// of every string that can appear there must fit the element's column at AX5 within the shrink the element allows.
/// Sizes are Apple's AX5 Dynamic Type values for the text style each @ScaledMetric is relative to, capped as in code.
@Suite struct WordFitTests {
    static let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
    static let bold = root.appendingPathComponent("navigator/EmberNavigator/Fonts/Inter-Bold.ttf")
    static let regular = root.appendingPathComponent("navigator/EmberNavigator/Fonts/Inter-Regular.ttf")

    // iPhone 15/16/17 Pro class: 393 pt wide, 16 pt screen padding, 12 pt card padding, 14 pt button padding, 12 pt row gap.
    static let content: CGFloat = 393 - 32
    static let card: CGFloat = content - 24
    static let halfButton: CGFloat = (content - 12) / 2 - 28
    static let fullButton: CGFloat = content - 28

    /// (name, AX5 point size after the code's cap, allowed minimumScaleFactor, column, bold)
    struct Element { let name: String; let size: CGFloat; let minScale: CGFloat; let column: CGFloat; let bold: Bool }
    static let instruction = Element(name: "InstructionText", size: 44, minScale: 0.7, column: card, bold: true)        // title 28→58, cap 44 at AX
    static let homeName = Element(name: "Home name", size: 66, minScale: 0.6, column: card, bold: true)                 // title2 26→66
    static let chooseName = Element(name: "Choose refuge name", size: 40, minScale: 0.7, column: card, bold: true)     // cap 40
    static let orRow = Element(name: "Choose Or row", size: 28, minScale: 0.7, column: card - 40, bold: true)          // cap 28, after "Or"
    static let button = Element(name: "EmberButton (half width)", size: 40, minScale: 0.5, column: halfButton, bold: true)
    static let fullWidth = Element(name: "EmberButton (full width)", size: 40, minScale: 0.5, column: fullButton, bold: true)
    static let shelterRoom = Element(name: "Shelter room", size: 48, minScale: 0.6, column: card, bold: true)
    static let toggle = Element(name: "ToggleRow / SecondaryText", size: 58, minScale: 1.0, column: card - 70, bold: true) // title3 22→58, next to a switch
    static let pill = Element(name: "Map pill", size: 15, minScale: 1.0, column: 393 - 60, bold: true)

    static let buttonTitles = ["Add profile", "Back", "Blocked", "Can't move", "Can't tell", "Cancel", "Done", "Go", "New fire", "No",
                               "Not sure", "OK", "Other", "Power is out", "Repeat", "Save", "Settings", "Start", "Yes", "Speak", "Next", "Louder"]
    static let headings = ["Who are you moving?", "Add a profile from the plan card.", "Point the camera at the code on the card.",
                           NavigatorStateMachine.whichWaySmoke, NavigatorStateMachine.whichWayNewFire, "Settings",
                           "Oxygen battery may be out. Leave now.", "Spoken instructions are in English.",
                           "Stay here. Help is on the way.", "You have arrived. Tell the people here what you need."]
    static let settingsLabels = ["Demo: step through route", "I am pushing the chair", "Font", "Map", "Start over"]
    static let settingsButtons = ["Hyperlegible", "Inter", "System", "Rounded", "Satellite", "Drawn"]   // half-width EmberButtons

    func check(_ e: Element, _ strings: [String]) -> [String] {
        guard let f = WordFit.font(url: e.bold ? Self.bold : Self.regular, size: e.size) else { return ["font missing"] }
        var bad: [String] = []
        for s in strings {
            let need = WordFit.neededScale(s, font: f, column: e.column)
            if need < e.minScale - 0.001 {
                let (w, px) = WordFit.widestWord(s, font: f)
                bad.append("\(e.name): \"\(w)\" is \(Int(px)) pt at \(Int(e.size)) pt, column \(Int(e.column)), needs ×\(String(format: "%.2f", need)) < ×\(e.minScale)")
            }
        }
        return bad
    }

    static func registryNames() -> [String] {
        var out: [String] = []
        for f in ["staff/sample_registry.csv", "staff/sample_registry_paradise.csv"] {
            guard let t = try? String(contentsOf: root.appendingPathComponent(f), encoding: .utf8) else { continue }
            for line in t.split(separator: "\n").dropFirst() {
                let cols = line.split(separator: ",", omittingEmptySubsequences: false)
                if cols.count > 1 { out.append(String(cols[1])) }
            }
        }
        return out
    }

    @Test func buttonsNeverBreak() {
        #expect(check(Self.button, Self.buttonTitles).isEmpty)
        #expect(check(Self.fullWidth, ["New fire", "Go", "Start"]).isEmpty)
    }

    @Test func homeNamesNeverBreak() {
        let names = Self.registryNames() + ["Margaret O'Neil", "Lupe Vang", "Bartholomew Featherstonehaugh"]
        let bad = check(Self.homeName, names.filter { $0 != "Bartholomew Featherstonehaugh" })
        #expect(bad.isEmpty, "\(bad)")
        // the absurd name is the negative case: at 66 pt it cannot fit even shrunk to 0.6 → the check must say so
        #expect(!check(Self.homeName, ["Bartholomew Featherstonehaugh"]).isEmpty)
    }

    @Test func refugeNamesAndInstructionsNeverBreak() {
        let b = Fixtures.bundle
        let names = b.refuges.map(\.name), short = b.refuges.map(\.shortName)
        var bad = check(Self.chooseName, short) + check(Self.orRow, short) + check(Self.pill, short)
        bad += check(Self.instruction, names.map { "Arrive at \($0)." } + Self.headings)
        bad += check(Self.shelterRoom, ["bedroom", "bathroom", "kitchen", "living room", "hallway"])
        #expect(bad.isEmpty, "\(bad)")
    }

    @Test func caregiverInfoNeverBreaks() {
        // CaregiverInfo rows: body-relative 18 → capped at 22 at AX sizes, icon + 8 pt gap, no shrink
        let e = Element(name: "CaregiverInfo", size: 22, minScale: 1.0, column: Self.card - 60, bold: false)
        let bad = check(e, ["Transfers independently", "Slide board transfer", "One-person assist", "Two-person assist",
                            "Oxygen (4 h battery), Power chair", "Ventilator, CPAP", "Chair: by the front door", "No powered devices on file."])
        #expect(bad.isEmpty, "\(bad)")
    }

    @Test func settingsNeverBreak() {
        let bad = check(Self.toggle, Self.settingsLabels) + check(Self.button, Self.settingsButtons)
        #expect(bad.isEmpty, "\(bad)")
    }

    /// Navigate strip at the default size (owner rule: no "…" anywhere). Margaret's route is 119 minutes: three
    /// digits plus a four-digit "to next turn" distance did not fit the ladder's smallest step with the demo
    /// "Next" button and fell into a layout that truncated ("to next t…", "119…"). Every strip the walker route can
    /// show must fit whole at some ladder step, with and without the button.
    @Test func navigateStripNeverTruncatesForThreeDigitMinutes() {
        let worst: [(value: String, caption: String)] = [("1450 m", "to next turn"), ("119 min", "to go")]
        let typical: [(value: String, caption: String)] = [("710 m", "to next turn"), ("119 min", "to go")]
        let nextButton: CGFloat = 48
        for items in [worst, typical] {
            for trailing in [CGFloat(0), nextButton] {
                let s = WordFit.stripScale(items: items, fontURL: Self.bold, column: Self.card, trailing: trailing)
                #expect(s != nil, "\(items) with trailing \(trailing) fits no step of \(WordFit.stripScales)")
                #expect((s ?? 0) >= 0.6)
            }
        }
        // the smallest step is the texts' minimumScaleFactor: the fallback never has to go below it
        #expect(WordFit.stripScales.last == 0.6)
        // negative case: a ladder that stops at 0.7 (the old one) cannot hold the worst strip next to the button
        let old = WordFit.stripWidth(items: worst, fontURL: Self.bold, scale: 0.7, trailing: nextButton) ?? 0
        #expect(old > Self.card)
    }

    /// AX5 Navigate strip (Margaret, low vision): the strip is one text run that wraps at word boundaries, and the
    /// number must stay with its unit: "710 m" / "to next turn", never "710" / "m to" (seen on the Simulator at AX5).
    /// At AX5 the big font is title2 26 → 66 pt; the widest unbreakable unit must still fit the card column.
    @Test func navigateStripKeepsNumberAndUnitTogetherAtAX5() throws {
        let v = WordFit.stripValue(710, unit: "m")
        #expect(!v.contains(" ") && v.contains(WordFit.nbsp))
        let big = try #require(WordFit.font(url: Self.bold, size: 66))
        #expect(WordFit.widestWord("\(v) to next turn", font: big).0 == v)
        for value in [WordFit.stripValue(1450, unit: "m"), WordFit.stripValue(119, unit: "min")] {
            let (w, px) = WordFit.widestWord(value + " to next turn", font: big)
            #expect(w == value && px <= Self.card, "\(w) is \(Int(px)) pt at 66 pt, column \(Int(Self.card))")
        }
    }
}
