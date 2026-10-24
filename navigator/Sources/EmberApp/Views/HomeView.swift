import SwiftUI
import EmberCore

struct HomeView: View {
    @EnvironmentObject var model: AppModel
    @State private var scanning = false
    @State private var settings = false
    @ScaledMetric(relativeTo: .title2) var nameSize: CGFloat = 26

    var body: some View {
        Screen {
            InstructionText(text: model.profiles.isEmpty ? "Add a profile from the plan card." : "Who are you moving?")
            ForEach(model.profiles) { p in
                Button { model.select(p.id) } label: {
                    HStack(spacing: 12) {
                        Image(systemName: icon(p)).font(.system(size: nameSize))
                        VStack(alignment: .leading) {
                            Text(p.name).font(.system(size: nameSize, weight: .bold))
                            Text(p.mobilityLabel).font(.system(size: nameSize * 0.75))
                        }
                        Spacer()
                        if p.id == model.selectedId {
                            Label("Selected", systemImage: "checkmark.circle.fill").font(.system(size: nameSize * 0.75, weight: .bold))
                        }
                    }
                    .foregroundColor(Theme.text)
                    .padding(12)
                    .frame(maxWidth: .infinity, minHeight: Theme.minButtonHeight)
                    .overlay(RoundedRectangle(cornerRadius: 12).stroke(Theme.text, lineWidth: p.id == model.selectedId ? 4 : 1))
                }
                .accessibilityLabel("\(p.name), \(p.mobilityLabel)\(p.id == model.selectedId ? ", selected" : "")")
                .accessibilityHint("Select who you are moving")
            }
            Toggle(isOn: $model.caregiverMode) {
                SecondaryText(text: "I am pushing the chair")
            }
            .tint(Theme.accent)
            .frame(minHeight: Theme.minButtonHeight)
            .accessibilityLabel("I am pushing the chair")
            Toggle(isOn: Binding(get: { model.powerIsOut }, set: { model.setPowerOut($0) })) {
                SecondaryText(text: "Power is out")
            }
            .tint(Theme.accent)
            .frame(minHeight: Theme.minButtonHeight)
            .accessibilityLabel("Power is out")
            .accessibilityHint("Starts the battery timer for oxygen and other devices")
            Label(model.fireAgeText + (model.fireIsStale ? " (old)" : ""), systemImage: "clock")
                .font(.system(size: nameSize * 0.8, weight: .semibold)).foregroundColor(Theme.text)
                .accessibilityLabel(model.fireAgeText + (model.fireIsStale ? ", old" : ""))
            if let note = model.feedNote { SecondaryText(text: note) }
            if let err = model.loadError { SecondaryText(text: err) }
            if let n = model.notice { SecondaryText(text: n) }
        } buttons: {
            EmberButton(title: "Start", systemImage: "play.fill", hint: "Find a safe place to go") { model.start() }
                .disabled(model.selected == nil || model.bundle == nil)
            HStack(spacing: 12) {
                EmberButton(title: "Add profile", systemImage: "qrcode.viewfinder", hint: "Scan the QR code on the plan card") { scanning = true }
                EmberButton(title: "Settings", systemImage: "gearshape", hint: "API keys, entered once at install") { settings = true }
            }
        }
        .sheet(isPresented: $scanning) {
            VStack(spacing: 12) {
                InstructionText(text: "Point the camera at the code on the card.")
                QRScanner { code in
                    scanning = false
                    model.addProfile(fromCode: code)
                }
                EmberButton(title: "Cancel", systemImage: "xmark") { scanning = false }
            }
            .padding(16)
            .background(Theme.background.ignoresSafeArea())
        }
        .sheet(isPresented: $settings) { SettingsView { settings = false; model.settingsChanged() } }
    }

    func icon(_ p: ClientProfile) -> String {
        switch p.mobility {
        case "manual_chair", "power_chair": return "figure.roll"
        case "walker", "cane": return "figure.walk"
        case "bedbound": return "bed.double.fill"
        default: return "person.fill"
        }
    }
}

struct SettingsView: View {
    let close: () -> Void
    @State private var values: [KeychainStore.Key: String] = [:]

    static let labels: [KeychainStore.Key: String] = [
        .anthropicAPIKey: "Anthropic API key", .cartesiaAPIKey: "Cartesia API key", .cartesiaVoiceId: "Cartesia voice id",
        .apifyToken: "Apify token", .apifyDatasetId: "Apify county feed dataset id",
    ]

    var body: some View {
        Screen {
            InstructionText(text: "Keys stay on this phone.")
            ForEach(KeychainStore.Key.allCases, id: \.self) { k in
                VStack(alignment: .leading) {
                    SecondaryText(text: SettingsView.labels[k] ?? k.rawValue)
                    SecureField(SettingsView.labels[k] ?? k.rawValue, text: Binding(get: { values[k] ?? "" }, set: { values[k] = $0 }))
                        .textFieldStyle(.roundedBorder)
                        .frame(minHeight: 44)
                        .accessibilityLabel(SettingsView.labels[k] ?? k.rawValue)
                }
            }
        } buttons: {
            EmberButton(title: "Save", systemImage: "checkmark") {
                for k in KeychainStore.Key.allCases { KeychainStore.set(k, values[k]) }
                close()
            }
            EmberButton(title: "Cancel", systemImage: "xmark") { close() }
        }
        .background(Theme.background.ignoresSafeArea())
        .onAppear {
            for k in KeychainStore.Key.allCases { values[k] = KeychainStore.get(k) ?? "" }
        }
    }
}
