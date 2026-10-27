import Foundation
import Testing
@testable import EmberCore

/// Walter Briggs (bedbound, ventilator): shelter-in-place only, never a route, never "stay in the open".
@Suite struct BedboundTests {
    /// A bedbound client cannot move, so a GPS fix away from the card's address (another client's demo position,
    /// a bad fix, the phone carried to a venue) must still give the shelter script, never the Stay-here screen.
    @Test func bedboundAwayFromHomeStillGetsTheShelterScript() throws {
        let m = NavigatorStateMachine(bundle: Fixtures.bundle)
        let g = Fixtures.bundle.graph
        let far = (0..<g.lat.count).first { Geo.haversineM(g.lat[0], g.lon[0], g.lat[$0], g.lon[$0]) > 500 }!
        m.setPosition(lat: g.lat[far], lon: g.lon[far])
        try m.start(client: Fixtures.client("bedbound"), caregiver: false)
        #expect(m.awayFromHome)
        #expect(m.state == .shelter)
        #expect(m.utterances.map(\.text) == ["Go to the back bedroom."])
        m.handle(.cantMove)
        #expect(m.state == .shelter)
    }
}
