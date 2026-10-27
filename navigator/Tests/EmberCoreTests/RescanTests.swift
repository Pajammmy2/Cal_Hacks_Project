import Foundation
import Testing
@testable import EmberCore

/// A card scanned mid-route (another client's or the same client's deep link while on Navigate or Arrived) left the
/// old route / Arrived screen up. The machine goes back to Home, silently (the app announces the card), and the next
/// Start begins the new run from the top.
@Suite struct RescanTests {
    let fresh = Timestamps.parse("2026-10-23T13:00:00Z")!

    func navigating() throws -> NavigatorStateMachine {
        let m = NavigatorStateMachine(bundle: Fixtures.bundle)
        m.clock = { [fresh] in fresh }
        try m.start(client: Fixtures.client("manual_chair", node: 0), caregiver: false)
        m.point(bearing: 200)
        m.go()
        #expect(m.state == .navigate)
        return m
    }

    @Test func cardScannedOnNavigateReturnsHomeSilently() throws {
        let m = try navigating()
        let serial = m.serial
        m.cardScanned()
        #expect(m.state == .home && m.progress == nil && m.pending == nil)
        #expect(m.utterances.isEmpty && m.serial == serial + 1, "the old route's speech stops; nothing else is said")
    }

    @Test func cardScannedWhileStoppedOrArrivedAlsoReturnsHome() throws {
        let m = try navigating()
        m.handle(.stop)
        #expect(m.stopped)
        m.cardScanned()
        #expect(m.state == .home && !m.stopped)
    }

    @Test func startAfterARescanBeginsTheNewClientsRunFromTheTop() throws {
        let m = try navigating()
        m.cardScanned()
        try m.start(client: Fixtures.client("bedbound"), caregiver: true)
        #expect(m.state == .shelter && m.shelterIndex == 0)
        m.cardScanned()
        try m.start(client: Fixtures.client("bedbound"), caregiver: true)
        #expect(m.state == .shelter && m.shelterIndex == 0, "the same card again restarts cleanly")
    }
}
