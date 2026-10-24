import SwiftUI
import EmberCore

struct WhichWayView: View {
    @EnvironmentObject var model: AppModel
    @EnvironmentObject var speaker: Speaker
    @EnvironmentObject var compass: CompassService

    var body: some View {
        let fresh = !model.fireIsStale && model.fireBearingWord != nil
        Screen {
            InstructionText(text: model.displayText)
            CompassArrow(fireBearing: fresh ? model.machine?.dataFireBearing : nil, heading: compass.heading)
                .frame(maxWidth: .infinity)
            if !fresh { SecondaryText(text: model.fireAgeText) }
        } buttons: {
            if fresh {
                EmberButton(title: "OK", systemImage: "checkmark", hint: "The fire is to the \(model.fireBearingWord ?? "")") { model.confirmFire() }
            }
            EmberButton(title: compass.heading == nil ? "Point (no compass)" : "Point", systemImage: "location.north.line.fill",
                        hint: "Hold the phone flat, point the top at the smoke, then tap") { model.pointAtSmoke() }
                .disabled(compass.heading == nil)
        }
    }
}

/// Big arrow. With fresh data it points at the fire (relative to the phone); otherwise straight ahead, to aim at smoke.
struct CompassArrow: View {
    let fireBearing: Double?
    let heading: Double?
    @ScaledMetric(relativeTo: .largeTitle) var size: CGFloat = 180

    var angle: Double {
        guard let f = fireBearing else { return 0 }
        return f - (heading ?? 0)
    }

    var label: String {
        if let f = fireBearing { return "Arrow points toward the fire, \(Int(f.rounded())) degrees" }
        if let h = heading { return "Phone points \(Int(h.rounded())) degrees" }
        return "No compass"
    }

    var body: some View {
        VStack(spacing: 8) {
            Image(systemName: fireBearing == nil ? "location.north.fill" : "flame.fill")
                .font(.system(size: size * 0.25))
            Image(systemName: "arrow.up")
                .font(.system(size: size, weight: .black))
                .rotationEffect(.degrees(angle))
                .animation(.easeOut(duration: 0.2), value: angle)
            if let h = heading { Text("\(Int(h.rounded()))°").font(.system(size: size * 0.18, weight: .bold)) }
        }
        .foregroundColor(Theme.accent)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(label)
    }
}

struct ChooseView: View {
    @EnvironmentObject var model: AppModel
    @ScaledMetric(relativeTo: .title) var big: CGFloat = 28
    @ScaledMetric(relativeTo: .title3) var small: CGFloat = 20

    var body: some View {
        let a = model.machine?.currentChoice
        let b = model.machine?.alternateChoice
        Screen {
            if let a {
                Text(a.refuge.name).font(.system(size: big, weight: .heavy)).foregroundColor(Theme.text)
                    .fixedSize(horizontal: false, vertical: true)
                Text("\(a.route.minutes) minutes").font(.system(size: big, weight: .bold)).foregroundColor(Theme.text)
                if let url = model.bundle?.thumbURL(a.refuge), let img = Platform.image(at: url) {
                    img.resizable().scaledToFit().frame(maxHeight: 220).clipShape(RoundedRectangle(cornerRadius: 12))
                        .accessibilityLabel("Photo of \(a.refuge.name) from above")
                }
                if let b {
                    Text("or \(b.refuge.name), \(b.route.minutes) minutes").font(.system(size: small, weight: .semibold))
                        .foregroundColor(Theme.text).fixedSize(horizontal: false, vertical: true)
                }
            }
        } buttons: {
            EmberButton(title: "Go", systemImage: "arrow.forward", hint: "Start directions to \(a?.refuge.name ?? "")") { model.go() }
            HStack(spacing: 12) {
                EmberButton(title: "Other", systemImage: "arrow.triangle.2.circlepath", hint: "Offer the next place") { model.other() }
                    .disabled(b == nil)
                EmberButton(title: "Can't move", systemImage: "house.fill", hint: "Start the shelter steps") { model.cantMove() }
            }
        }
    }
}

struct NavigateView: View {
    @EnvironmentObject var model: AppModel
    @EnvironmentObject var speaker: Speaker
    @EnvironmentObject var voice: VoiceController

    var body: some View {
        let m = model.machine
        let p = m?.progress
        Screen {
            InstructionText(text: model.displayText)
            if let d = p?.distanceToNextTurnM {
                SecondaryText(text: "Next turn in \(Int((d / 10).rounded()) * 10) meters")
            }
            HStack(alignment: .top, spacing: 16) {
                VStack(alignment: .leading, spacing: 4) {
                    let mins = Int(ceil((m?.remainingRouteTimeS ?? 0) / 60))
                    Label("\(mins) min to go", systemImage: "figure.roll").font(.title3.bold())
                    if let eta = m?.fireETAMinutes {
                        Label("Fire about \(Int(eta.rounded())) min away", systemImage: "flame").font(.title3.bold())
                        if Double(mins) >= eta { Label("Fire may arrive first", systemImage: "exclamationmark.triangle.fill").font(.title3.weight(.heavy)) }
                    } else {
                        Label("fire ETA unknown", systemImage: "flame").font(.title3)
                    }
                }
                .foregroundColor(Theme.text)
                .accessibilityElement(children: .combine)
            }
            if let m, let p { RouteMapView(graph: m.graph, route: p.route, position: m.position, refuge: m.currentChoice?.refuge) }
            CaregiverInfo(client: m?.client)
            if voice.listening { SecondaryText(text: voice.partial.isEmpty ? "Listening…" : voice.partial) }
        } buttons: {
            HStack(spacing: 12) {
                EmberButton(title: "Blocked", systemImage: "xmark.octagon.fill", hint: "Find a way around") { model.blocked() }
                EmberButton(title: "Repeat", systemImage: "speaker.wave.2.fill", hint: "Say the instruction again") { model.repeatInstruction() }
            }
            HStack(spacing: 12) {
                EmberButton(title: "Can't move", systemImage: "house.fill", hint: "Start the shelter steps") { model.cantMove() }
                EmberButton(title: voice.listening ? "Done" : "Speak", systemImage: voice.listening ? "mic.fill" : "mic",
                            hint: "Say blocked, repeat, where am I, or how long") { model.micTapped() }
            }
        }
    }
}

struct ShelterView: View {
    @EnvironmentObject var model: AppModel
    @EnvironmentObject var speaker: Speaker
    @ScaledMetric(relativeTo: .largeTitle) var roomSize: CGFloat = 60

    var body: some View {
        let m = model.machine
        Screen {
            if let room = m?.shelter.room {
                Text(room).font(.system(size: roomSize, weight: .black)).foregroundColor(Theme.text)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityLabel("Room: \(room)")
            }
            InstructionText(text: model.displayText)
            if let m { SecondaryText(text: "Step \(m.shelterIndex + 1) of \(m.shelter.steps.count)") }
            CaregiverInfo(client: m?.client)
        } buttons: {
            EmberButton(title: "Next", systemImage: "arrow.forward", hint: "Next step") { model.shelterNext() }
            HStack(spacing: 12) {
                EmberButton(title: "Repeat", systemImage: "speaker.wave.2.fill", hint: "Say this step again") { model.repeatInstruction() }
                EmberButton(title: "Back", systemImage: "arrow.backward", hint: "Previous step") { model.shelterBack() }
            }
        }
    }
}

struct ArrivedView: View {
    @EnvironmentObject var model: AppModel
    @EnvironmentObject var speaker: Speaker

    var body: some View {
        Screen {
            Image(systemName: "checkmark.seal.fill").font(.system(size: 80)).foregroundColor(Theme.accent)
                .accessibilityHidden(true)
            InstructionText(text: model.displayText)
        } buttons: {
            EmberButton(title: "Done", systemImage: "checkmark", hint: "Back to the start screen") { model.done() }
        }
    }
}
