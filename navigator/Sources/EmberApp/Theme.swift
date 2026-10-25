import SwiftUI

/// Near-black navy / white / steel blue: white on the card (#0D1A33) is ~17:1, navy text on steel blue (#94B5D6) ~9.5:1, both above 7:1.
/// Green is used only on the map for the refuge area, never as the sole carrier of meaning.
public enum Theme {
    public static let background = Color(red: 0.015, green: 0.035, blue: 0.09)
    public static let text = Color.white
    public static let dim = Color(red: 0.74, green: 0.80, blue: 0.88)
    public static let accent = Color(red: 0.58, green: 0.71, blue: 0.84)
    public static let onAccent = Color(red: 0.01, green: 0.03, blue: 0.08)
    public static let card = Color(red: 0.05, green: 0.10, blue: 0.20)
    public static let cardRaised = Color(red: 0.09, green: 0.16, blue: 0.29)
    public static let land = Color(red: 0.16, green: 0.17, blue: 0.18)
    public static let safe = Color(red: 0.30, green: 0.80, blue: 0.45)
    /// The route on the map: bright sky blue with a black casing, unmistakable on the veiled photo and on the drawn map.
    public static let route = Color(red: 0.55, green: 0.85, blue: 1.0)
    /// Dark navy veil over the satellite photo (look A "Signal"): photo still readable, overlays win.
    public static let mapVeil = Color(red: 0.01, green: 0.03, blue: 0.08).opacity(0.42)
    /// Look C "Blueprint": navy land, steel roads, drawn from graph.json (offline / no photo / Settings → Map).
    public static let mapLand = Color(red: 0.04, green: 0.08, blue: 0.16)
    public static let mapRoadMinor = Color(red: 0.36, green: 0.46, blue: 0.58)
    public static let mapRoadMajor = Color(red: 0.62, green: 0.72, blue: 0.84)
    public static let minButtonHeight: CGFloat = 64
    /// "satellite" (default, look A) | "drawn" (look C). Settings → Map.
    public static let mapStyleKey = "ember.mapStyle"

    /// "inter" (default, bundled) | "system" | "rounded" | "hyperlegible" (Atkinson Hyperlegible, bundled). Both custom fonts are OFL. Settings → Font.
    public static let fontKey = "ember.font"
    public static var fontChoice: String { UserDefaults.standard.string(forKey: fontKey) ?? "inter" }
    public static func font(_ size: CGFloat, _ weight: Font.Weight = .regular) -> Font {
        let bold: Set<Font.Weight> = [.semibold, .bold, .heavy, .black]
        switch fontChoice {
        case "hyperlegible": return .custom(bold.contains(weight) ? "AtkinsonHyperlegible-Bold" : "AtkinsonHyperlegible-Regular", size: size)
        case "system": return .system(size: size, weight: weight)
        case "rounded": return .system(size: size, weight: weight, design: .rounded)
        default: return .custom(bold.contains(weight) ? "Inter-Bold" : "Inter-Regular", size: size)
        }
    }
    public static let corner: CGFloat = 18
}

/// Sizes scale with Dynamic Type up to the largest accessibility size.
struct ScaledFonts {
    @ScaledMetric(relativeTo: .title) var instruction: CGFloat = 28
    @ScaledMetric(relativeTo: .largeTitle) var room: CGFloat = 60
    @ScaledMetric(relativeTo: .title3) var secondary: CGFloat = 22
    @ScaledMetric(relativeTo: .body) var body: CGFloat = 20
}

/// Icon + title on one line; the title shrinks (to 60 %) rather than wrapping.
struct SingleLineLabelStyle: LabelStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(spacing: 8) {
            configuration.icon
            configuration.title
                .lineLimit(1)
                .minimumScaleFactor(0.5)
                .allowsTightening(true)
        }
    }
}

/// The one button style. Text never wraps: one line, scaled down if the title is long.
struct EmberButtonStyle: ButtonStyle {
    @ScaledMetric(relativeTo: .title2) var size: CGFloat = 24
    @Environment(\.isEnabled) var enabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(Theme.font(min(size, 40), .bold))
            .labelStyle(SingleLineLabelStyle())
            .lineLimit(1)
            .minimumScaleFactor(0.5)
            .foregroundColor(enabled ? Theme.onAccent : Theme.dim)
            .padding(.horizontal, 14)
            .frame(maxWidth: .infinity, minHeight: Theme.minButtonHeight)
            .background(enabled ? Theme.accent : Theme.card)
            .overlay(RoundedRectangle(cornerRadius: Theme.corner, style: .continuous)
                .stroke(Theme.dim.opacity(enabled ? 0 : 0.7), lineWidth: 2))
            .clipShape(RoundedRectangle(cornerRadius: Theme.corner, style: .continuous))
            .opacity(configuration.isPressed ? 0.75 : 1)
            .scaleEffect(configuration.isPressed ? 0.98 : 1)
            .animation(.easeOut(duration: 0.1), value: configuration.isPressed)
    }
}

struct EmberButton: View {
    let title: String
    let systemImage: String
    var hint: String? = nil
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Label(title, systemImage: systemImage)
        }
        .buttonStyle(EmberButtonStyle())
        .accessibilityLabel(title)
        .accessibilityHint(hint ?? "")
    }
}

/// Two buttons side by side; at accessibility text sizes they stack so no title has to shrink past readability.
struct ButtonRow<Content: View>: View {
    @Environment(\.dynamicTypeSize) var typeSize
    @ViewBuilder let content: Content

    var body: some View {
        if typeSize.isAccessibilitySize {
            VStack(spacing: 12) { content }
        } else {
            HStack(spacing: 12) { content }
        }
    }
}

struct CardModifier: ViewModifier {
    var fill: Color
    var padding: CGFloat

    func body(content: Content) -> some View {
        content
            .padding(padding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(fill)
            .clipShape(RoundedRectangle(cornerRadius: Theme.corner, style: .continuous))
    }
}

extension View {
    /// Dark-grey rounded card behind a block of text or controls.
    func card(_ fill: Color = Theme.card, padding: CGFloat = 16) -> some View {
        modifier(CardModifier(fill: fill, padding: padding))
    }
}

/// The instruction sentence: 28 pt, white on a dark card, never truncated.
struct InstructionText: View {
    let text: String
    @ScaledMetric(relativeTo: .title) var size: CGFloat = 28

    var body: some View {
        Text(text)
            .font(Theme.font(size, .bold))
            .foregroundColor(Theme.text)
            .multilineTextAlignment(.leading)
            .fixedSize(horizontal: false, vertical: true)
            .card()
            .accessibilityAddTraits(.updatesFrequently)
    }
}

struct SecondaryText: View {
    let text: String
    @ScaledMetric(relativeTo: .title3) var size: CGFloat = 22

    var body: some View {
        Text(text)
            .font(Theme.font(size, .semibold))
            .foregroundColor(Theme.text)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// A note or status line on its own card (feed notes, errors, "listening…").
struct NoteText: View {
    let text: String
    var systemImage: String? = nil
    @ScaledMetric(relativeTo: .title3) var size: CGFloat = 20

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            if let systemImage { Image(systemName: systemImage).font(Theme.font(size, .semibold)) }
            Text(text).fixedSize(horizontal: false, vertical: true)
        }
        .font(Theme.font(size, .semibold))
        .foregroundColor(Theme.text)
        .card(padding: 14)
    }
}

/// A big number with a unit and a caption, for distance and time on Navigate.
struct StatTile: View {
    let value: String
    let unit: String
    let caption: String
    let systemImage: String
    var warning = false
    @ScaledMetric(relativeTo: .largeTitle) var big: CGFloat = 44
    @ScaledMetric(relativeTo: .body) var small: CGFloat = 17

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(alignment: .firstTextBaseline, spacing: 4) {
                Text(value).font(Theme.font(big, .heavy))
                Text(unit).font(Theme.font(small * 1.2, .bold))
            }
            .lineLimit(1)
            .minimumScaleFactor(0.5)
            Label(caption, systemImage: systemImage)
                .font(Theme.font(small, .semibold))
                .lineLimit(2)
                .minimumScaleFactor(0.7)
        }
        .foregroundColor(warning ? Theme.onAccent : Theme.text)
        .card(warning ? Theme.accent : Theme.card, padding: 14)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(value) \(unit) \(caption)")
    }
}
