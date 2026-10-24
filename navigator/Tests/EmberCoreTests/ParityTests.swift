import Foundation
import Testing
@testable import EmberCore

/// Router, cues, card steps, clip keys and geo helpers must equal the Python core on bundles/fake
/// (engine/tests/parity/dump_parity.py), because Cartesia audio is generated in Python and looked up by sha1.
@Suite struct ParityTests {
    static let dump: [String: Any] = {
        let d = try! Data(contentsOf: Fixtures.parityURL)
        return try! JSONSerialization.jsonObject(with: d) as! [String: Any]
    }()

    static func close(_ a: Double, _ b: Double) -> Bool {
        a == b || abs(a - b) <= 1e-6 * max(abs(a), abs(b))
    }

    @Test func routesCuesAndCardSteps() throws {
        let b = Fixtures.bundle
        let cuesB = Cues(graph: b.graph, config: Fixtures.config)
        let cases = Self.dump["cases"] as! [[String: Any]]
        #expect(cases.count > 300)
        var compared = 0
        for c in cases {
            let origin = c["origin"] as! Int
            let prof = Fixtures.profile(c["profile"] as! String, battery: (c["battery_pct"] as! NSNumber).doubleValue)
            let fb = (c["fire_bearing"] as? NSNumber)?.doubleValue
            let per = c["perimeter"] as? [[Double]]
            let blocked = Set(c["blocked"] as! [Int])
            let got = Router.choose(b.graph, refuges: b.refuges, profile: prof, origin: origin, fireBearing: fb,
                                    perimeter: per, blocked: blocked)
            let want = c["choices"] as! [[String: Any]]
            let label = "\(c["profile"]!) o=\(origin) \(c["scenario"]!)"
            try #require(got.count == want.count, "choice count \(label)")
            for (g, w) in zip(got, want) {
                #expect(g.refuge.id == w["refuge_id"] as! String, "\(label)")
                let wr = w["route"] as! [String: Any]
                #expect(g.route.nodes == wr["nodes"] as! [Int], "\(label)")
                #expect(g.route.edges == wr["edges"] as! [Int], "\(label)")
                #expect(g.route.forward == wr["forward"] as! [Bool], "\(label)")
                #expect(Self.close(g.route.timeS, (wr["time_s"] as! NSNumber).doubleValue), "\(label)")
                #expect(Self.close(g.route.lengthM, (wr["length_m"] as! NSNumber).doubleValue), "\(label)")
                #expect(g.route.minutes == wr["minutes"] as! Int, "\(label)")

                let cl = cuesB.buildCues(g.route, refugeName: g.refuge.name)
                let wc = w["cues"] as! [[String: Any]]
                try #require(cl.count == wc.count, "cue count \(label)")
                for (x, y) in zip(cl, wc) {
                    #expect(x.template == y["template"] as! String)
                    #expect(x.text == y["text"] as! String)
                    #expect(Hashing.clipKey(x.text) == y["key"] as! String)
                    #expect(Self.close(x.distanceM, (y["distance_m"] as! NSNumber).doubleValue), "\(label) \(x.text)")
                    #expect(x.node == y["node"] as! Int)
                    let wv = y["vars"] as! [String: Any]
                    #expect(Set(x.vars.keys) == Set(wv.keys))
                    for (k, v) in wv {
                        if let s = v as? String { #expect(x.vars[k] == .str(s)) } else { #expect(x.vars[k] == .int((v as! NSNumber).intValue)) }
                    }
                }
                #expect(Cues.cardSteps(cl) == w["card_steps"] as! [String], "\(label)")
                compared += 1
            }
        }
        #expect(compared > 1000)
    }

    @Test func snaps() {
        let g = Fixtures.bundle.graph
        for s in Self.dump["snaps"] as! [[String: Any]] {
            let p = Fixtures.profile(s["profile"] as! String)
            let r = g.snap((s["lat"] as! NSNumber).doubleValue, (s["lon"] as! NSNumber).doubleValue, usable: Router.usableOrigin(g, p))
            #expect(r.node == s["node"] as? Int)
            #expect(Self.close(r.distance, (s["d"] as! NSNumber).doubleValue))
        }
    }

    @Test func hashesAndPronunciation() {
        for h in Self.dump["hashes"] as! [[String: Any]] {
            let t = h["text"] as! String
            #expect(Hashing.normalize(t) == h["normalized"] as! String)
            #expect(Hashing.clipKey(t) == h["key"] as! String)
            #expect(Hashing.forCartesia(t, pronunciation: Fixtures.config.pronunciation) == h["cartesia"] as! String)
        }
    }

    @Test func geoHelpersBitForBit() {
        for x in Self.dump["geo"] as! [[String: Any]] {
            let p = (x["p"] as! [NSNumber]).map(\.doubleValue)
            #expect(Geo.haversineM(p[0], p[1], p[2], p[3]) == (x["haversine"] as! NSNumber).doubleValue)
            #expect(Geo.bearingDeg(p[0], p[1], p[2], p[3]) == (x["bearing"] as! NSNumber).doubleValue)
        }
        for x in Self.dump["turns"] as! [[String: Any]] {
            let a = (x["a"] as! NSNumber).doubleValue, b = (x["b"] as! NSNumber).doubleValue
            #expect(Geo.angdiff(a, b) == (x["angdiff"] as! NSNumber).doubleValue)
            #expect(Geo.signedTurn(a, b) == (x["signed"] as! NSNumber).doubleValue)
            #expect(Geo.directionWord(a, Fixtures.config.templates.directions) == x["word"] as! String)
        }
    }
}
