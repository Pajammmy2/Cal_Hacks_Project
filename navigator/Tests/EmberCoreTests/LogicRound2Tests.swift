import Foundation
import Testing
@testable import EmberCore

/// Round-2 logic items: blind users skip the visual compass, the shelter flow ends in Done -> Home, and the phone
/// offers the card's refuges first.
@Suite struct LogicRound2Tests {
    let fresh = Timestamps.parse("2026-10-23T13:00:00Z")!

    func machine() -> NavigatorStateMachine {
        let m = NavigatorStateMachine(bundle: Fixtures.bundle)
        m.clock = { fresh }
        return m
    }

    @Test func blindClientSkipsWhichWayAndHearsTheFirstOption() throws {
        let m = machine()
        var c = Fixtures.client("manual_chair", node: 112)
        c.vision = "blind"
        try m.start(client: c, caregiver: false)
        #expect(m.state == .choose)
        let a = try #require(m.currentChoice)
        #expect(m.utterances.first?.text == "Go to \(a.refuge.name). \(a.route.minutes) minutes.")
        #expect(m.fireBearing == 45)   // fresh fire data is still used for the wedge
    }

    @Test func sightedClientStillGetsWhichWay() throws {
        let m = machine()
        try m.start(client: Fixtures.client("manual_chair", node: 112), caregiver: false)
        #expect(m.state == .whichWay)
    }

    @Test func shelterLastStepIsDoneAndGoesHome() throws {
        let m = machine()
        try m.start(client: Fixtures.client("bedbound"), caregiver: true)
        #expect(m.state == .shelter)
        let n = m.shelter.steps.count
        #expect(n == 6)
        for _ in 1..<n { m.shelterNext() }
        #expect(m.shelterIsLastStep)
        #expect(m.shelterIndex == n - 1)
        m.shelterNext()                                  // the button reads "Done" here
        #expect(m.state == .home)
        #expect(m.progress == nil)
    }

    @Test func shelterBackFromFirstStepGoesHomeToo() throws {
        let m = machine()
        try m.start(client: Fixtures.client("bedbound"), caregiver: true)
        m.shelterBack()
        #expect(m.state == .home)
    }

    @Test func singleMinuteIsSingularAndPastRatedHoursSaysMayBeOut() {
        let one = DeviceTimer.Remaining(kind: "oxygen", label: "Oxygen", hoursLeft: 1.0 / 60.0)
        #expect(DeviceTimer.leaveNowSentence(one, config: Fixtures.config) == "Leave now. Oxygen has 1 minute left.")
        let gone = DeviceTimer.Remaining(kind: "oxygen", label: "Oxygen", hoursLeft: 0)
        #expect(DeviceTimer.leaveNowSentence(gone, config: Fixtures.config) == "Oxygen battery may be out. Leave now.")
    }
}
