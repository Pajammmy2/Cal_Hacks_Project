import SwiftUI

/// Black / white / yellow only: white on black is 21:1, black on yellow (#FFD60A) is ~14:1, both above 7:1.
/// Meaning is never carried by color alone; every state also has words and an icon.
public enum Theme {
    public static let background = Color.black
    public static let text = Color.white
    public static let accent = Color(red: 1.0, green: 0.84, blue: 0.04)
    public static let onAccent = Color.black
    public static let minButtonHeight: CGFloat = 64
}

/// Sizes scale with Dynamic Type up to the largest accessibility size.
struct ScaledFonts {
    @ScaledMetric(relativeTo: .title) var instruction: CGFloat = 28
    @ScaledMetric(relativeTo: .largeTitle) var room: CGFloat = 60
    @ScaledMetric(relativeTo: .title3) var secondary: CGFloat = 22
    @ScaledMetric(relativeTo: .body) var body: CGFloat = 20
}

/// The one button style.
struct EmberButtonStyle: ButtonStyle {
    @ScaledMetric(relativeTo: .title2) var size: CGFloat = 24
    @Environment(\.isEnabled) var enabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: size, weight: .bold))
            .multilineTextAlignment(.center)
            .foregroundColor(enabled ? Theme.onAccent : Theme.text)
            .frame(maxWidth: .infinity, minHeight: Theme.minButtonHeight)
            .padding(.horizontal, 12)
            .background(enabled ? Theme.accent : Theme.background)
            .overlay(RoundedRectangle(cornerRadius: 14).stroke(Theme.accent, lineWidth: enabled ? 0 : 3))
            .clipShape(RoundedRectangle(cornerRadius: 14))
            .opacity(configuration.isPressed ? 0.75 : 1)
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

/// The instruction sentence: 28 pt, white on black, never truncated.
struct InstructionText: View {
    let text: String
    @ScaledMetric(relativeTo: .title) var size: CGFloat = 28

    var body: some View {
        Text(text)
            .font(.system(size: size, weight: .bold))
            .foregroundColor(Theme.text)
            .multilineTextAlignment(.leading)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
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
