import Testing
@testable import EmberCore

@Suite struct HapticCueTests {
    func cue(_ template: String, side: String? = nil) -> Cue {
        Cue(template: template, vars: side.map { ["side": .str($0)] } ?? [:], text: "", distanceM: 0, node: 0)
    }

    @Test func turnsMapBySide() {
        #expect(HapticCue.forCue(cue("turn", side: "left")) == .left)
        #expect(HapticCue.forCue(cue("turn_slight", side: "right")) == .right)
        #expect(HapticCue.forCue(cue("turn_sharp", side: "left")) == .left)
        #expect(HapticCue.forCue(cue("continue")) == .straight)
        #expect(HapticCue.forCue(cue("start")) == .straight)
        #expect(HapticCue.forCue(cue("arrive")) == .arrived)
        #expect(HapticCue.forCue(cue("shelter_step")) == nil)
    }

    @Test func patternsAreDistinctAndCountable() {
        let patterns = HapticCue.allCases.map(\.pulses)
        #expect(Set(patterns.map { "\($0)" }).count == patterns.count)   // no two cues feel the same
        #expect(HapticCue.left.pulses.count == 2)
        #expect(HapticCue.right.pulses.count == 3)
        #expect(HapticCue.straight.pulses.allSatisfy { $0.strength == .heavy && $0.gapS < 0.1 })   // reads as one buzz
        #expect(HapticCue.offRoute.pulses[0].gapS >= 0.4)
        #expect(HapticCue.legend.contains("Two taps") && HapticCue.legend.contains("Three taps"))
    }
}
