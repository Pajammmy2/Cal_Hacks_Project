import SwiftUI
import EmberCore

/// One screen at a time, chosen by the state machine. "Leave now" sits on top of every screen.
public struct RootView: View {
    @EnvironmentObject var model: AppModel

    public init() {}

    public var body: some View {
        VStack(spacing: 0) {
            if let text = model.leaveNow { LeaveNowBanner(text: text) }
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
        .environmentObject(model.speaker)
        .environmentObject(model.compass)
        .environmentObject(model.voice)
        .preferredColorScheme(.dark)
        .onAppear { model.launch() }
    }
}

struct LeaveNowBanner: View {
    let text: String
    @ScaledMetric(relativeTo: .title) var size: CGFloat = 28

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Label("Leave now.", systemImage: "exclamationmark.triangle.fill")
                .font(.system(size: size, weight: .heavy))
            Text(text).font(.system(size: size * 0.7, weight: .semibold)).fixedSize(horizontal: false, vertical: true)
        }
        .foregroundColor(Theme.onAccent)
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(Theme.accent)
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
            VStack(alignment: .leading, spacing: 2) {
                Label(c.transferLabel, systemImage: "figure.roll")
                Label(c.equipmentLabel, systemImage: "bolt.heart")
                if let chair = c.home?.chairLocation, !chair.isEmpty { Label("Chair: \(chair)", systemImage: "house") }
            }
            .font(.system(size: size, weight: .medium))
            .foregroundColor(Theme.text)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(10)
            .overlay(RoundedRectangle(cornerRadius: 10).stroke(Theme.text, lineWidth: 1))
            .accessibilityElement(children: .combine)
            .accessibilityLabel("For the helper: \(c.transferLabel). Equipment: \(c.equipmentLabel).")
        }
    }
}

struct Screen<Content: View, Buttons: View>: View {
    @ViewBuilder let content: Content
    @ViewBuilder let buttons: Buttons

    var body: some View {
        VStack(spacing: 16) {
            ScrollView { VStack(alignment: .leading, spacing: 16) { content }.padding(.top, 8) }
            VStack(spacing: 12) { buttons }
        }
        .padding(16)
    }
}
