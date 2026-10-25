import SwiftUI
import EmberCore

/// One screen at a time, chosen by the state machine. "Leave now" sits on top of every screen.
public struct RootView: View {
    @EnvironmentObject var model: AppModel
    @AppStorage(Theme.fontKey) private var fontChoice = "inter"
    @AppStorage(Theme.paletteKey) private var palette = "navy"

    public init() {}

    public var body: some View {
        VStack(spacing: 0) {
            if let text = model.leaveNow { LeaveNowBanner(text: text).padding([.horizontal, .top], 12) }
            Group {
                switch model.state {
                case .home: HomeView()
                case .whichWay: WhichWayView()
                case .choose: ChooseView()
                case .navigate: NavigateView()
                case .shelter: ShelterView()
                case .arrived: ArrivedView()
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        }
        .background(Theme.background.ignoresSafeArea())
        .id(fontChoice + palette)   // fonts and colours are read statically; rebuild the tree when either changes
        .environmentObject(model.speaker)
        .environmentObject(model.compass)
        .environmentObject(model.voice)
        .preferredColorScheme(Theme.isLight ? .light : .dark)
        .onAppear { model.launch() }
    }
}

struct LeaveNowBanner: View {
    let text: String
    @ScaledMetric(relativeTo: .title) var size: CGFloat = 28

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Label("Leave now.", systemImage: "exclamationmark.triangle.fill")
                .font(Theme.font(size, .heavy))
            Text(text).font(Theme.font(size * 0.7, .semibold)).fixedSize(horizontal: false, vertical: true)
        }
        .foregroundColor(Theme.onAccent)
        .card(Theme.accent, padding: 14)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Leave now. \(text)")
        .accessibilityAddTraits(.isHeader)
    }
}

/// Transfer method and equipment, for whoever is moving the client, without asking.
struct CaregiverInfo: View {
    let client: ClientProfile?
    @ScaledMetric(relativeTo: .body) var size: CGFloat = 18

    var body: some View {
        if let c = client {
            VStack(alignment: .leading, spacing: 6) {
                Label(c.transferLabel, systemImage: "figure.roll")
                Label(c.equipmentLabel, systemImage: "bolt.heart")
                if let chair = c.home?.chairLocation, !chair.isEmpty { Label("Chair: \(chair)", systemImage: "house") }
            }
            .font(Theme.font(size, .medium))
            .foregroundColor(Theme.text)
            .card(padding: 12)
            .accessibilityElement(children: .combine)
            .accessibilityLabel("For the helper: \(c.transferLabel). Equipment: \(c.equipmentLabel).")
        }
    }
}

/// Content above, buttons pinned below. `scrolls: false` lets a flexible child (the map) take the spare height.
struct Screen<Content: View, Buttons: View>: View {
    var scrolls = true
    @ViewBuilder let content: Content
    @ViewBuilder let buttons: Buttons

    var body: some View {
        VStack(spacing: 16) {
            if scrolls {
                ScrollView(showsIndicators: false) {
                    VStack(alignment: .leading, spacing: 12) { content }.padding(.top, 4)
                }
            } else {
                VStack(alignment: .leading, spacing: 12) { content }.padding(.top, 4)
                    .frame(maxHeight: .infinity, alignment: .top)
            }
            VStack(spacing: 12) { buttons }
        }
        .padding(16)
    }
}
