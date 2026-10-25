import Testing
import Foundation
@testable import EmberCore

@Suite struct FollowCameraTests {
    let t0 = Date(timeIntervalSince1970: 1_700_000_000)

    @Test func overviewThenFollowAfterOneSecond() {
        var c = FollowCamera(now: t0)
        #expect(c.mode == .overview && !c.isFollowing && !c.showsRecentre)
        #expect(c.tick(now: t0.addingTimeInterval(0.5)) == false)
        #expect(c.mode == .overview)
        #expect(c.tick(now: t0.addingTimeInterval(FollowCamera.overviewS)) == true)
        #expect(c.mode == .follow && c.isFollowing)
        #expect(c.tick(now: t0.addingTimeInterval(5)) == false)          // no second transition
    }

    @Test func handOnTheMapPausesUntilRecentre() {
        var c = FollowCamera(now: t0)
        c.tick(now: t0.addingTimeInterval(2))
        c.userInteracted()
        #expect(c.mode == .paused && c.showsRecentre && !c.isFollowing)
        #expect(c.tick(now: t0.addingTimeInterval(60)) == false)         // time never un-pauses
        #expect(c.mode == .paused)
        c.recentre()
        #expect(c.mode == .follow && !c.showsRecentre)
    }

    @Test func pauseDuringOverviewAlsoSticks() {
        var c = FollowCamera(now: t0)
        c.userInteracted()
        #expect(c.tick(now: t0.addingTimeInterval(10)) == false)
        #expect(c.mode == .paused)
    }

    @Test func reenteringNavigateShowsTheWholeRouteAgain() {
        var c = FollowCamera(now: t0)
        c.tick(now: t0.addingTimeInterval(2))
        c.userInteracted()
        c.reset(now: t0.addingTimeInterval(100))
        #expect(c.mode == .overview)
        #expect(c.tick(now: t0.addingTimeInterval(100.5)) == false)
        #expect(c.tick(now: t0.addingTimeInterval(101.0)) == true)
    }

    @Test func viewportNorthUpWithoutHeadingHeadingUpWithOne() {
        #expect(FollowCamera.viewport(lat: nil, lon: nil, heading: 90) == nil)
        let nu = FollowCamera.viewport(lat: 39.75, lon: -121.61, heading: nil)!
        #expect(nu.rotationDeg == 0 && nu.lat == 39.75 && nu.lon == -121.61 && nu.spanM == FollowCamera.followSpanM)
        let hu = FollowCamera.viewport(lat: 39.75, lon: -121.61, heading: 90)!
        #expect(hu.rotationDeg == 90)
        // centred ahead (east) of the user by aheadFraction of the span
        let aheadM = Geo.haversineM(39.75, -121.61, hu.lat, hu.lon)
        #expect(abs(aheadM - FollowCamera.followSpanM * FollowCamera.aheadFraction) < 1.0)
        #expect(hu.lon > -121.61 && abs(hu.lat - 39.75) < 1e-6)
        let n = FollowCamera.viewport(lat: 39.75, lon: -121.61, heading: 360 + 0.0)!
        #expect(n.rotationDeg == 0 && n.lat > 39.75)
    }

    @Test func overviewSpanCoversEveryPoint() {
        let pts = [(lat: 39.7485, lon: -121.6153), (lat: 39.7600, lon: -121.6153)]   // ~1.28 km north-south
        let span = FollowCamera.overviewSpanM(points: pts, aspect: 1.0)
        #expect(span > 1280 * 1.3 && span < 1280 * 1.5)
        #expect(FollowCamera.overviewSpanM(points: [], aspect: 1) == FollowCamera.followSpanM)
        #expect(FollowCamera.overviewSpanM(points: [pts[0]], aspect: 1) >= 40)
    }
}
