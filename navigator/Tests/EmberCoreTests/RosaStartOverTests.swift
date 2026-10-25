import Foundation
import Testing
@testable import EmberCore

/// Owner addendum: after a demo-stepped run reached Arrived, a new start (Done → Start, re-scan, Start over → Start)
/// must begin at the client's home with the full route time, never "arrived". Real Paradise bundle, c_rosa.
@Suite struct RosaStartOverTests {
    static let real = ProcessInfo.processInfo.environment["EMBER_REAL_BUNDLE"].map { URL(fileURLWithPath: $0) }

    /// Refuge A and its minutes on the very first start: every later start must offer the same route again.
    var firstChoice: (String, Int)?

    mutating func demoToArrived(_ m: NavigatorStateMachine) throws {
        try m.start(client: RosaFuzzAudioTests.rosa(), caregiver: false)
        m.point(bearing: 90)
        firstChoice = m.choices.first.map { ($0.refuge.id, $0.route.minutes) }
        m.go()
        #expect(m.state == .navigate)
        m.demoStepping = true
        var n = 0
        while m.state == .navigate, n < 50 { _ = m.demoStep(); n += 1 }
        #expect(m.state == .arrived)
        m.demoStepping = false
    }

    func expectFreshStart(_ m: NavigatorStateMachine, _ label: String) {
        #expect(m.state == .whichWay, "\(label): state \(m.state)")
        m.point(bearing: 90)
        #expect(m.state == .choose, "\(label)")
        #expect(m.choices.first?.refuge.id == firstChoice?.0 && m.choices.first?.route.minutes == firstChoice?.1,
                "\(label): \(String(describing: m.choices.first.map { ($0.refuge.id, $0.route.minutes) })) vs first \(String(describing: firstChoice))")
        #expect(m.blocked.isEmpty, "\(label): blocked roads survived")
        m.go()
        #expect(m.state == .navigate, "\(label): \(m.state)")
        #expect(m.progress?.progressM == 0, "\(label): progress \(String(describing: m.progress?.progressM))")
        #expect(m.progress?.groupIndex == 0)
        #expect(Int(ceil((m.remainingRouteTimeS ?? 0) / 60)) == firstChoice?.1, "\(label): remaining \(String(describing: m.remainingRouteTimeS))")
    }

    @Test(.enabled(if: real != nil))
    mutating func doneThenStartBeginsAtHome() throws {
        let m = NavigatorStateMachine(bundle: try EmberBundle(dir: RosaStartOverTests.real!, sharedFallback: Fixtures.sharedDir))
        try demoToArrived(m)
        m.done()
        #expect(m.state == .home)
        try m.start(client: RosaFuzzAudioTests.rosa(), caregiver: false)
        expectFreshStart(m, "Done → Start")
    }

    @Test(.enabled(if: real != nil))
    mutating func rescanAfterArrivedBeginsAtHome() throws {
        let m = NavigatorStateMachine(bundle: try EmberBundle(dir: RosaStartOverTests.real!, sharedFallback: Fixtures.sharedDir))
        try demoToArrived(m)
        // Re-scanning the card = start(client:) with the same profile, straight from Arrived.
        try m.start(client: RosaFuzzAudioTests.rosa(), caregiver: false)
        expectFreshStart(m, "re-scan")
    }

    @Test(.enabled(if: real != nil))
    mutating func startOverMidRouteWithBlockedRoadsThenStartIsFresh() throws {
        let m = NavigatorStateMachine(bundle: try EmberBundle(dir: RosaStartOverTests.real!, sharedFallback: Fixtures.sharedDir))
        try m.start(client: RosaFuzzAudioTests.rosa(), caregiver: false)
        m.point(bearing: 90)
        firstChoice = m.choices.first.map { ($0.refuge.id, $0.route.minutes) }
        m.go()
        m.demoStepping = true; _ = m.demoStep(); m.demoStepping = false
        #expect(m.state == .navigate)
        m.requestBlocked()
        #expect(m.utterances.map(\.text) == [NavigatorStateMachine.rerouteQuestion])
        m.confirmPending()
        #expect(!m.blocked.isEmpty)
        m.requestStartOver()
        #expect(m.utterances.map(\.text) == [NavigatorStateMachine.startOverQuestion])
        m.confirmPending()
        #expect(m.state == .home)
        #expect(m.progress == nil)
        try m.start(client: RosaFuzzAudioTests.rosa(), caregiver: false)
        expectFreshStart(m, "Start over → Start")
    }

    @Test func startOverFromHomeStaysHomeAndAnswers() {
        let m = NavigatorStateMachine(bundle: Fixtures.bundle)
        #expect(m.requestStartOver(), "the reset happened now: the app may clear its Power-out clock")
        #expect(m.state == .home && m.utterances.map(\.text) == [NavigatorStateMachine.okay])
    }

    /// Mid-run the machine only asks "Start over?"; the app must not clear its Power-out clock until the Yes.
    @Test func startOverMidRunOnlyAsks() throws {
        let m = NavigatorStateMachine(bundle: Fixtures.bundle)
        try m.start(client: Fixtures.client("walker"), caregiver: false)
        #expect(!m.requestStartOver())
        #expect(m.state == .whichWay && m.pending == .startOver)
    }
}
