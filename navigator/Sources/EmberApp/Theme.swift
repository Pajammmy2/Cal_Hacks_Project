import SwiftUI

/// Navy / white / light blue: white on the navy card (#142B52) is ~13:1, navy text on light blue (#8FCCFF) ~9:1, both above 7:1.
/// Green is used only on the map for the refuge area, never as the sole carrier of meaning.
public enum Theme {
    public static let background = Color(red: 0.03, green: 0.09, blue: 0.20)
    public static let text = Color.white
    public static let dim = Color(red: 0.78, green: 0.86, blue: 0.96)
    public static let accent = Color(red: 0.56, green: 0.80, blue: 1.0)
    public static let onAccent = Color(red: 0.02, green: 0.07, blue: 0.16)
    public static let card = Color(red: 0.08, green: 0.17, blue: 0.32)
    public static let cardRaised = Color(red: 0.13, green: 0.25, blue: 0.43)
    public static let land = Color(red: 0.16, green: 0.17, blue: 0.18)
    public static let safe = Color(red: 0.30, green: 0.80, blue: 0.45)
    public static let minButtonHeight: CGFloat = 64
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
            .font(.system(size: min(size, 40), weight: .bold))
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
            .font(.system(size: size, weight: .bold))
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
            .font(.system(size: size, weight: .semibold))
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
            if let systemImage { Image(systemName: systemImage).font(.system(size: size, weight: .semibold)) }
            Text(text).fixedSize(horizontal: false, vertical: true)
        }
        .font(.system(size: size, weight: .semibold))
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
                Text(value).font(.system(size: big, weight: .heavy, design: .rounded))
                Text(unit).font(.system(size: small * 1.2, weight: .bold))
            }
            .lineLimit(1)
            .minimumScaleFactor(0.5)
            Label(caption, systemImage: systemImage)
                .font(.system(size: small, weight: .semibold))
                .lineLimit(2)
                .minimumScaleFactor(0.7)
        }
        .foregroundColor(warning ? Theme.onAccent : Theme.text)
        .card(warning ? Theme.accent : Theme.card, padding: 14)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(value) \(unit) \(caption)")
    }
}
