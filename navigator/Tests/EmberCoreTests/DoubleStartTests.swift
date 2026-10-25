import Foundation
import Testing
@testable import EmberCore

/// Home "Start" tapped twice in one gesture (Walter, bedbound, Simulator): the second tap reached the machine as a
/// second start() and the shelter script began again, or (once the screen had switched) as shelter "Next", so step 1
/// was skipped. A repeated Start within TapGuard.settleS of the first is the same tap: step 1 is spoken once and
/// the flow begins at step 1. A deliberate Start later still restarts from the top.
@Suite struct DoubleStartTests {
    @Test func doubleTapStartForABedboundClientSpeaksStepOneOnce() throws {
        let m = NavigatorStateMachine(bundle: Fixtures.bundle)
        var now = Date()
        m.clock = { now }
        let walter = Fixtures.client("bedbound")
        try m.start(client: walter, caregiver: true)
        let step1 = try #require(m.shelter.steps.first)
        #expect(m.state == .shelter && m.shelterIndex == 0)
        #expect(m.utterances.map(\.text) == [step1] && m.serial == 1)
        now += 0.2
        try m.start(client: walter, caregiver: true)
        #expect(m.state == .shelter && m.shelterIndex == 0, "second half of the double tap moved the script")
        #expect(m.serial == 1, "second half of the double tap spoke step 1 again")
        m.shelterNext()
        #expect(m.shelterIndex == 1)
        now += 5
        try m.start(client: walter, caregiver: true)
        #expect(m.shelterIndex == 0 && m.utterances.map(\.text) == [step1], "a deliberate Start later begins at step 1")
    }

    @Test func doubleTapStartForAWalkerAsksWhichWayOnce() throws {
        let m = NavigatorStateMachine(bundle: Fixtures.bundle)
        var now = Date()
        m.clock = { now }
        try m.start(client: Fixtures.client("walker"), caregiver: false)
        let first = m.serial
        #expect(m.state == .whichWay && first == 1)
        now += 0.3
        try m.start(client: Fixtures.client("walker"), caregiver: false)
        #expect(m.serial == first && m.state == .whichWay)
        now += 1
        try m.start(client: Fixtures.client("walker"), caregiver: false)
        #expect(m.serial == first + 1)
    }
}
