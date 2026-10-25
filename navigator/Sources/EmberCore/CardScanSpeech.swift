import Foundation

/// What the phone says after a card is scanned (QR or `ember://p/...` deep link). Every sentence here is one the
/// bundle has a recorded clip for: "Added <name>." is recorded per client of the county; a card from another county,
/// or a phone with no bundle, gets the recorded card-mismatch line instead of an ad-hoc sentence through the system
/// voice (the on-screen notice may still explain which county the map is for).
public enum CardScanSpeech {
    public static let notACard = "That code is not an Ember card. Try again."

    public static func added(_ name: String) -> String { "Added \(name)." }

    public static func spoken(card: ClientProfile?, bundleCounty: String?) -> String {
        guard let card else { return notACard }
        if let county = bundleCounty, card.county == county { return added(card.name) }
        return NavigatorStateMachine.cardMismatch
    }
}
