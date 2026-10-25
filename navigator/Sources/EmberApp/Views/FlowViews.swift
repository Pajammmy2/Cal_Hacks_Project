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
                .padding(.vertical, 8)
            if !fresh { NoteText(text: model.fireAgeText + (model.fireIsStale ? " (old)" : ""), systemImage: "clock.badge.exclamationmark") }
        } buttons: {
            if fresh {
                EmberButton(title: "OK", systemImage: "checkmark", hint: "The fire is to the \(model.fireBearingWord ?? "")") { model.confirmFire() }
            }
            if compass.heading != nil {
                EmberButton(title: "Point", systemImage: "location.north.line.fill",
                            hint: "Hold the phone flat, point the top at the smoke, then tap") { model.pointAtSmoke() }
            }
            if !fresh {
                // Old data and no compass used to dead-end here. The plan's refuges are still safe choices.
                EmberButton(title: "Not sure", systemImage: "questionmark.circle",
                            hint: "Skip the fire direction and choose from the planned safe places") { model.skipFireDirection() }
            }
        }
    }
}

/// Big arrow on a dial. With fresh data it points at the fire (relative to the phone); otherwise straight ahead, to aim at smoke.
struct CompassArrow: View {
    let fireBearing: Double?
    let heading: Double?
    @ScaledMetric(relativeTo: .largeTitle) var scaled: CGFloat = 170
    /// Capped so the dial always fits the screen width at accessibility sizes.
    var size: CGFloat { min(scaled, 200) }

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
        VStack(spacing: 10) {
            ZStack {
                Circle().fill(Theme.card)
                Circle().stroke(Theme.cardRaised, lineWidth: 3)
                ForEach(0..<4, id: \.self) { i in
                    Rectangle().fill(Theme.dim).frame(width: 3, height: size * 0.08)
                        .offset(y: -size * 0.66)
                        .rotationEffect(.degrees(Double(i) * 90))
                }
                Image(systemName: "arrow.up")
                    .font(Theme.font(size * 0.75, .black))
                    .rotationEffect(.degrees(angle))
                    .animation(.easeOut(duration: 0.2), value: angle)
            }
            .frame(width: size * 1.45, height: size * 1.45)
            HStack(spacing: 8) {
                Image(systemName: fireBearing == nil ? "location.north.fill" : "flame.fill")
                Text(fireBearing == nil ? "Aim the top of the phone" : "Fire")
                if let h = heading { Text("· \(Int(h.rounded()))°") }
            }
            .font(Theme.font(size * 0.14, .bold))
            .lineLimit(1)
            .minimumScaleFactor(0.6)
        }
        .foregroundColor(Theme.accent)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(label)
    }
}

struct ChooseView: View {
    @EnvironmentObject var model: AppModel
    @EnvironmentObject var voice: VoiceController
    @ScaledMetric(relativeTo: .title) var big: CGFloat = 28
    @ScaledMetric(relativeTo: .title3) var small: CGFloat = 20
    @Environment(\.dynamicTypeSize) var typeSize

    var body: some View {
        let m = model.machine
        let a = m?.currentChoice
        let b = m?.alternateChoice
        let header = typeSize.isAccessibilitySize ? AnyLayout(VStackLayout(alignment: .leading, spacing: 6)) : AnyLayout(HStackLayout(alignment: .firstTextBaseline))
        Screen {
            if let a, let m {
                VStack(alignment: .leading, spacing: 10) {
                    header {
                        Label("Go here", systemImage: "arrow.forward.circle.fill")
                            .font(Theme.font(small, .bold)).foregroundColor(Theme.accent)
                        if !typeSize.isAccessibilitySize { Spacer() }
                        Label("\(a.route.minutes) min", systemImage: "figure.roll")
                            .font(Theme.font(small, .bold)).foregroundColor(Theme.text)
                    }
                    .lineLimit(1).minimumScaleFactor(0.7)
                    Text(a.refuge.name).font(Theme.font(big * 1.15, .heavy)).foregroundColor(Theme.text)
                        .fixedSize(horizontal: false, vertical: true)
                    RouteMapView(graph: m.graph, route: a.route, position: m.position, refuge: a.refuge,
                                 satellite: SatelliteSnapshot.best(for: a.route, graph: m.graph, bundle: model.bundle, clientId: m.client?.id),
                                 online: voice.online, thumbnail: true, height: typeSize.isAccessibilitySize ? 300 : 360)
                }
                .card(Theme.card)
                .overlay(RoundedRectangle(cornerRadius: Theme.corner, style: .continuous).stroke(Theme.accent, lineWidth: 3))
                if let b {
                    HStack(spacing: 12) {
                        RouteMapView(graph: m.graph, route: b.route, position: m.position, refuge: b.refuge,
                                     satellite: SatelliteSnapshot.best(for: b.route, graph: m.graph, bundle: model.bundle, clientId: m.client?.id),
                                     online: voice.online, thumbnail: true, height: 140)
                            .frame(width: 150)
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Or").font(Theme.font(small, .semibold)).foregroundColor(Theme.dim)
                            Text(b.refuge.name).font(Theme.font(small * 1.3, .bold)).foregroundColor(Theme.text)
                                .fixedSize(horizontal: false, vertical: true)
                            Text("\(b.route.minutes) min").font(Theme.font(small * 1.2, .bold)).foregroundColor(Theme.dim)
                        }
                        Spacer(minLength: 0)
                    }
                    .card(padding: 12)
                    .accessibilityElement(children: .combine)
                    .accessibilityLabel("Or \(b.refuge.name), \(b.route.minutes) minutes. Tap Other to choose it.")
                }
            }
        } buttons: {
            EmberButton(title: "Go", systemImage: "arrow.forward", hint: "Start directions to \(a?.refuge.name ?? "")") { model.go() }
            ButtonRow {
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
    @EnvironmentObject var compass: CompassService
    @Environment(\.dynamicTypeSize) var typeSize

    var body: some View {
        let m = model.machine
        let p = m?.progress
        let mins = Int(ceil((m?.remainingRouteTimeS ?? 0) / 60))
        let eta = m?.fireETAMinutes
        let fireFirst = eta.map { Double(mins) >= $0 } ?? false
        let tiles = typeSize.isAccessibilitySize ? AnyLayout(VStackLayout(spacing: 10)) : AnyLayout(HStackLayout(alignment: .top, spacing: 10))
        Screen {
            InstructionText(text: model.displayText)
            tiles {
                if let d = p?.distanceToNextTurnM {
                    StatTile(value: "\(Int((d / 10).rounded()) * 10)", unit: "m", caption: "to next turn", systemImage: "arrow.turn.up.right")
                }
                StatTile(value: "\(mins)", unit: "min", caption: "to go", systemImage: "figure.roll")
            }
            // Only a real number helps here: an unknown fire ETA used to take a third of the row as "?".
            if let eta {
                StatTile(value: "\(Int(eta.rounded()))", unit: "min", caption: fireFirst ? "Fire may arrive first" : "until fire reaches you",
                         systemImage: fireFirst ? "exclamationmark.triangle.fill" : "flame", warning: fireFirst)
            }
            if let m, let p {
                RouteMapView(graph: m.graph, route: p.route, position: m.position, refuge: m.currentChoice?.refuge,
                             heading: compass.heading, walkedM: p.progressM,
                             satellite: SatelliteSnapshot.best(for: p.route, graph: m.graph, bundle: model.bundle, clientId: m.client?.id),
                             online: voice.online)
                    .frame(height: typeSize.isAccessibilitySize ? 320 : 400)
            }
            CaregiverInfo(client: m?.client)
            if voice.listening { NoteText(text: voice.partial.isEmpty ? "Listening…" : voice.partial, systemImage: "waveform") }
        } buttons: {
            ButtonRow {
                EmberButton(title: "Blocked", systemImage: "xmark.octagon.fill", hint: "Find a way around") { model.blocked() }
                EmberButton(title: "Repeat", systemImage: "speaker.wave.2.fill", hint: "Say the instruction again") { model.repeatInstruction() }
            }
            ButtonRow {
                EmberButton(title: "Can't move", systemImage: "house.fill", hint: "Start the shelter steps") { model.cantMove() }
                EmberButton(title: voice.listening ? "Done" : "Speak", systemImage: voice.listening ? "mic.fill" : "mic",
                            hint: "Say blocked, fire, repeat, where am I, or how long") { model.micTapped() }
            }
            ButtonRow {
                EmberButton(title: "New fire", systemImage: "flame.fill", hint: "Point the phone at the fire, then tap") { model.pointAtNewFire() }
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
                Text(room).font(Theme.font(roomSize, .black)).foregroundColor(Theme.onAccent)
                    .fixedSize(horizontal: false, vertical: true)
                    .card(Theme.accent)
                    .accessibilityLabel("Room: \(room)")
            }
            InstructionText(text: model.displayText)
            if let m { NoteText(text: "Step \(m.shelterIndex + 1) of \(m.shelter.steps.count)", systemImage: "list.number") }
            CaregiverInfo(client: m?.client)
        } buttons: {
            EmberButton(title: "Next", systemImage: "arrow.forward", hint: "Next step") { model.shelterNext() }
            ButtonRow {
                EmberButton(title: "Repeat", systemImage: "speaker.wave.2.fill", hint: "Say this step again") { model.repeatInstruction() }
                EmberButton(title: "Back", systemImage: "arrow.backward", hint: "Previous step") { model.shelterBack() }
            }
        }
    }
}

struct ArrivedView: View {
    @EnvironmentObject var model: AppModel
    @EnvironmentObject var speaker: Speaker
    @ScaledMetric(relativeTo: .largeTitle) var badge: CGFloat = 72

    var body: some View {
        Screen {
            HStack(spacing: 14) {
                Image(systemName: "checkmark.seal.fill").font(Theme.font(badge)).foregroundColor(Theme.accent)
                Text("You made it.").font(Theme.font(badge * 0.5, .heavy)).foregroundColor(Theme.text)
                    .lineLimit(1).minimumScaleFactor(0.6)
                Spacer(minLength: 0)
            }
            .card()
            .accessibilityElement(children: .combine)
            InstructionText(text: model.displayText)
        } buttons: {
            EmberButton(title: "Done", systemImage: "checkmark", hint: "Back to the start screen") { model.done() }
        }
    }
}
