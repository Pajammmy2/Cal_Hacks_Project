import Foundation
import Testing
@testable import EmberCore

/// A card from another county (`ember://p/fake/...` on a Paradise phone, or a county with no bundle) made the app
/// speak "Added X. The map on this phone is for paradise, not fake." through the Apple voice: unrecorded. Only recorded
/// sentences may be spoken on the scan path.
/// EMBER_REAL_BUNDLE=/path/to/bundles/paradise swift test --filter CardScanSpeech
@Suite struct CardScanSpeechTests {
    static let real = ProcessInfo.processInfo.environment["EMBER_REAL_BUNDLE"]

    @Test func offCountyOrNoBundleCardSpeaksTheRecordedMismatchLine() throws {
        let card = try QRPayload.parse(QRPayload.make(Fixtures.client("walker"), county: "fake"))
        #expect(CardScanSpeech.spoken(card: card, bundleCounty: "paradise") == NavigatorStateMachine.cardMismatch)
        #expect(CardScanSpeech.spoken(card: card, bundleCounty: nil) == NavigatorStateMachine.cardMismatch)
        #expect(CardScanSpeech.spoken(card: card, bundleCounty: "fake") == "Added Test Client.")
        #expect(CardScanSpeech.spoken(card: nil, bundleCounty: "fake") == CardScanSpeech.notACard)
    }

    /// The sentences the scan path can say for a card that is not this bundle's are fixed phrases of every bundle.
    @Test func scanPathSentencesAreFixedPhrases() {
        let fixed = Set(Fixtures.bundle.config.phrases.fixed)
        for s in [NavigatorStateMachine.cardMismatch, CardScanSpeech.notACard] {
            #expect(fixed.contains(s), "\(s) is not a recorded fixed phrase")
        }
    }

    /// Against the real bundle: a clip exists for every sentence the scan path can say, including every recorded
    /// "Added <name>." the bundle lists in audio/index.json.
    @Test(.enabled(if: real != nil))
    func everyScanPathSentenceHasAClip() throws {
        let b = try MargaretFuzzTests.bundle()
        var sentences = [NavigatorStateMachine.cardMismatch, CardScanSpeech.notACard]
        let index = try JSONDecoder().decode([String: String].self, from: Data(contentsOf: b.audioDir.appendingPathComponent("index.json")))
        sentences += index.values.filter { $0.hasPrefix("Added ") }
        #expect(sentences.count > 2)
        for s in sentences {
            #expect(MargaretFuzzTests.hasClip(Utterance(s), bundle: b, clientId: "c_none"), "no clip for \(s) (\(Hashing.clipKey(s)))")
        }
    }
}
