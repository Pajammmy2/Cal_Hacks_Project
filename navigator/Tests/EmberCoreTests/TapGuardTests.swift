import Foundation
import Testing
@testable import EmberCore

@Suite struct TapGuardTests {
    @Test func aTapRightAfterTheScreenChangedIsIgnored() {
        let shown = Date()
        #expect(!TapGuard.accepts(tapAt: shown.addingTimeInterval(0.12), screenShownAt: shown))   // the second half of a double tap
        #expect(!TapGuard.accepts(tapAt: shown.addingTimeInterval(0.3), screenShownAt: shown))
        #expect(TapGuard.accepts(tapAt: shown.addingTimeInterval(0.5), screenShownAt: shown))
        #expect(TapGuard.accepts(tapAt: shown.addingTimeInterval(2), screenShownAt: shown))
    }

    /// A double tap on Choose "Go" must not run Navigate "Can't move": the machine would be in Shelter.
    @Test func doubleTapOnGoDoesNotReachCantMoveOnTheNextScreen() throws {
        let m = NavigatorStateMachine(bundle: Fixtures.bundle)
        m.clock = { Timestamps.parse("2026-10-23T13:00:00Z")! }
        try m.start(client: Fixtures.client("walker", node: 112), caregiver: false)
        m.confirmFire()
        #expect(m.state == .choose)
        let t0 = Date()
        m.go()                                             // first tap: Choose -> Navigate, screen shown at t0
        #expect(m.state == .navigate)
        let second = t0.addingTimeInterval(0.1)
        if TapGuard.accepts(tapAt: second, screenShownAt: t0) { m.cantMove() }   // what AppModel.cantMove does
        #expect(m.state == .navigate)
    }
}
