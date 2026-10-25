import Foundation
import Testing
@testable import EmberCore

@Suite struct HashingTests {
    @Test func knownKeysMatchPython() {
        let known: [(String, String)] = [
            ("Say again?", "496990596a5efbf962ef71e82e45cc34c1a360c8"),
            ("Leave now.", "900974a7886e840fdf21a17ebe0b118f42f98363"),
            ("  Turn left onto Clark Rd. ", "19a06498def81d8974b9469c82edc35e9f27d80a"),
            ("Keep going on Skyway for 4 blocks.", "71bae4dd2410d73d035a66c380ef9aeac7757a71"),
            ("No route. Stay where you are. Start the shelter steps.", "ce25990198c427da573008de8cfcf6990e2798e5"),
            ("4", "1b6453892473a467d07372d45eb05abc2031647a"),
            ("Caf\u{e9}\u{a0}\u{2003}ol\u{e9}\u{1c} x", "338fe9616059812cb8c630e3f065dc73a091dffc"),
        ]
        for (t, k) in known { #expect(Hashing.clipKey(t) == k, "\(t)") }
    }

    @Test func pronunciationIsWholeWordAndKeyUnchanged() {
        let p = Fixtures.config.pronunciation
        #expect(Hashing.forCartesia("Turn left onto Skyway.", pronunciation: p) == "Turn left onto sky way.")
        #expect(Hashing.forCartesia("Drive to Rdx.", pronunciation: p) == "Drive to Rdx.")
    }
}

@Suite struct IntentTests {
    let m = IntentMatcher(Fixtures.config.intents)

    /// Spec: all 12 phrases plus three synonyms each, recognized on-device, plus `fire` (fire/smoke seen, not a physical block).
    static let required: [(Intent, [String])] = [
        (.blocked, ["blocked", "tree down", "can't get through", "road closed"]),
        (.fire, ["fire ahead", "fire", "smoke ahead", "smoke", "flames", "i see fire", "i see flames", "it's on fire", "fire up ahead"]),
        (.repeat, ["repeat", "say that again", "what did you say", "one more time"]),
        (.slower, ["slower", "slow down", "too fast", "speak slower"]),
        (.louder, ["louder", "can't hear", "speak up", "volume up"]),
        (.pushing, ["I'm pushing", "pushing the chair", "I am pushing", "im pushing"]),
        (.cantMove, ["can't move", "stuck", "we're trapped", "cannot move"]),
        (.whereAmI, ["where am I", "where are we", "what street", "location"]),
        (.howLong, ["how long", "how far", "how much longer", "how many minutes"]),
        (.whichWay, ["which way", "what direction", "where do I go", "which direction"]),
        (.stop, ["stop", "pause", "wait", "hold on"]),
        (.yes, ["yes", "yeah", "yep", "correct"]),
        (.no, ["no", "nope", "cancel", "don't"]),
    ]

    @Test func thirteenPhrasesPlusThreeSynonymsEach() {
        #expect(Self.required.count == 13)
        for (intent, phrases) in Self.required {
            for p in phrases {
                #expect(m.match(p)?.intent == intent, "\(p)")
                #expect(m.match("Um, \(p.uppercased()), please")?.intent == intent, "\(p) in a sentence")
            }
        }
    }

    @Test func everySynonymInTheFileMapsToItsIntent() {
        for (key, syns) in Fixtures.config.intents.intents {
            for s in syns { #expect(m.match(s)?.intent.rawValue == key, "\(s)") }
        }
    }

    @Test func longestPhraseWinsAndWordBoundaries() {
        #expect(m.match("there's a tree down on Clark")?.intent == .blocked)
        #expect(m.match("there's a car blocking the road")?.intent == .blocked)
        #expect(m.match("fire ahead")?.intent == .fire)
        #expect(m.match("I see smoke up there")?.intent == .fire)
        #expect(m.match("it\u{2019}s on fire")?.intent == .fire)
        #expect(m.match("there is fire on the road ahead")?.intent == .fire)
        #expect(m.match("flames")?.intent == .fire)
        #expect(m.match("no way through here")?.intent == .blocked)       // "no way through" beats "no"
        #expect(m.match("say that again")?.intent == .repeat)
        #expect(m.match("I can\u{2019}t move")?.intent == .cantMove)       // curly apostrophe from the recognizer
        #expect(m.match("okay")?.intent == .yes)
        #expect(m.match("nowhere") == nil)                                  // "no" only at word boundaries
        #expect(m.match("blockade")?.intent == nil)
        #expect(m.match("the weather is nice") == nil)
        #expect(m.match("") == nil)
    }
}

@Suite struct DeviceTimerTests {
    let t0 = Date(timeIntervalSince1970: 1_800_000_000)

    @Test func leaveNowWhenRemainingBelowRoutePlusOneHour() {
        var dt = DeviceTimer(devices: [ClientDevice(kind: "oxygen", hours: 3), ClientDevice(kind: "cpap"),
                                       ClientDevice(kind: "power_chair", batteryPct: 80)])
        #expect(dt.leaveNow(routeTimeS: 1800, now: t0) == nil)             // not running
        dt.powerOutSince = t0
        #expect(dt.remaining(now: t0).map(\.kind) == ["oxygen"])
        #expect(dt.leaveNow(routeTimeS: 1800, now: t0) == nil)             // 3 h left, need 1.5 h
        #expect(dt.leaveNow(routeTimeS: 1800, now: t0 + 1.4 * 3600) == nil) // 1.6 h left
        let r = dt.leaveNow(routeTimeS: 1800, now: t0 + 1.6 * 3600)        // 1.4 h left < 1.5 h
        #expect(r?.kind == "oxygen")
        #expect(DeviceTimer.leaveNowSentence(r!, config: Fixtures.config) == "Leave now. Oxygen has 84 minutes left.")
        #expect(dt.remaining(now: t0 + 10 * 3600).first?.hoursLeft == 0)
    }

    @Test func mostUrgentDeviceFirst() {
        let dt = DeviceTimer(devices: [ClientDevice(kind: "oxygen", hours: 6), ClientDevice(kind: "ventilator", hours: 2)],
                             powerOutSince: t0)
        #expect(dt.leaveNow(routeTimeS: 3600 * 1.5, now: t0)?.label == "Ventilator")
        #expect(DeviceTimer.labels == ["oxygen": "Oxygen", "ventilator": "Ventilator", "power_chair": "Power chair"])
        let chair = DeviceTimer(devices: [ClientDevice(kind: "power_chair", hours: 1)], powerOutSince: t0)
        let r = chair.leaveNow(routeTimeS: 600, now: t0)!
        #expect(DeviceTimer.leaveNowSentence(r, config: Fixtures.config) == "Leave now. Power chair has 60 minutes left.")
        let late = DeviceTimer.Remaining(kind: "oxygen", label: "Oxygen", hoursLeft: 4.5)
        #expect(DeviceTimer.leaveNowSentence(late, config: Fixtures.config) == "Leave now. Oxygen has 270 minutes left.")
    }
}

@Suite struct QRAndPlanTextTests {
    @Test func qrRoundTripAndBase64url() throws {
        let c = Fixtures.client("manual_chair", devices: [ClientDevice(kind: "oxygen", hours: 4)])
        let s = try QRPayload.make(c, county: "fake")
        #expect(s.hasPrefix("ember://p/fake/"))
        let p = try QRPayload.parse(s)
        #expect(try QRPayload.parse(s.trimmingCharacters(in: CharacterSet(charactersIn: "="))) == p)   // unpadded too
        #expect(p.id == c.id && p.name == c.name && p.county == "fake" && p.devices == c.devices)
        // A payload as the staff tool writes it (python json + urlsafe_b64encode without padding).
        let json = #"{"v":1,"id":"c_1","name":"Ana","mobility":"bedbound","transfer":"hoyer","devices":[],"vision":"normal","hearing":"normal","cognition":"none","language":"en","home":{"sleep_room":"front room","pets":"cat","chair_location":"hall"},"lat":39.75,"lon":-121.63,"refuge_ids":["r_kmart","r_safeway"]}"#
        let b64 = Data(json.utf8).base64EncodedString().replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
        #expect(b64.hasSuffix("="), "fixture exercises padding")
        let q = try QRPayload.parse("ember://p/paradise/\(b64)")
        #expect(q.county == "paradise" && q.isBedbound && q.refugeIds == ["r_kmart", "r_safeway"])
        #expect(throws: EmberError.self) { try QRPayload.parse("https://example.com") }
    }

    @Test func shelterAndDeviceTextMatchPlanPy() {
        let c = Fixtures.client("power_chair", devices: [ClientDevice(kind: "oxygen", hours: 4), ClientDevice(kind: "power_chair", batteryPct: 75),
                                                       ClientDevice(kind: "cpap"), ClientDevice(kind: "ventilator", hours: 2.5)])
        #expect(PlanText.shelterSteps(c).steps.first == "Go to the back bedroom.")
        #expect(PlanText.shelterSteps(c).steps.last == "Call 911. Say: I am in the back bedroom.")
        let d = PlanText.deviceSentences(c, routeMinutes: 25, fullRangeM: 20000).map(\.sentence)
        #expect(d == ["Your oxygen battery lasts about 4 hours. If the power goes out, leave while it has 1.5 hours left.",
                      "Charge your chair every night. At 75 percent it can go about 15 kilometers.",
                      "Your CPAP stops when the power goes out. Take it with you.",
                      "Your ventilator battery lasts about 2.5 hours. If the power goes out, leave while it has 1.5 hours left."])
    }
}

@Suite struct ZipTests {
    @Test func extractsTheFakeBundleZip() throws {
        let zip = Fixtures.repo.appendingPathComponent("bundles/fake.zip")
        let dest = FileManager.default.temporaryDirectory.appendingPathComponent("ember-zip-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: dest) }
        let files = try ZipArchive.extract(zip, to: dest)
        #expect(files.contains("fake/graph.json"))
        let a = try Data(contentsOf: dest.appendingPathComponent("fake/graph.json"))
        let b = try Data(contentsOf: Fixtures.fakeDir.appendingPathComponent("graph.json"))
        #expect(a == b)
        let loaded = try EmberBundle(dir: dest.appendingPathComponent("fake"))
        #expect(loaded.graph.edges.count == Fixtures.bundle.graph.edges.count)
    }
}
