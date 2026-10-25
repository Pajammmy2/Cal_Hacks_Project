import Foundation

/// A cue variable: Python formats ints with str() and strings as-is.
public enum CueVar: Sendable, Equatable, CustomStringConvertible {
    case int(Int)
    case str(String)
    public var description: String {
        switch self {
        case .int(let n): return String(n)
        case .str(let s): return s
        }
    }
    public var intValue: Int? { if case .int(let n) = self { return n }; return nil }
}

public struct Cue: Sendable, Equatable {
    public var template: String
    public var vars: [String: CueVar]
    public var text: String
    public var distanceM: Double
    public var node: Int
}

/// Port of engine/ember_engine/core/cues.py. Every string here is pre-generable for Cartesia.
public struct Cues {
    public static let slopeMinPct = 4.0
    public static let slopeMinLenM = 30.0

    public let graph: Graph
    public let config: SharedConfig

    public init(graph: Graph, config: SharedConfig) { self.graph = graph; self.config = config }

    public static func roundMeters(_ m: Double) -> Int {
        Int(min(500.0, max(10.0, Double(Py.roundInt(m / 10.0)) * 10)))
    }

    public static func displayName(_ e: Edge, _ t: TurnTemplates) -> String {
        if let n = e.name, !n.isEmpty { return n }
        if let rc = e.roadClass, t.pathClasses.contains(rc) { return t.unnamedPath }
        return t.unnamedStreet
    }

    public func displayName(_ e: Edge) -> String { Cues.displayName(e, config.templates) }

    func fill(_ key: String, _ vars: [String: CueVar], distance: Double, node: Int) -> Cue {
        let text = SharedConfig.format(config.templates[key] ?? "", vars.mapValues(\.description))
        return Cue(template: key, vars: vars, text: text, distanceM: distance, node: node)
    }

    public struct Leg {
        public var street: String
        public var edges: [Int] = []
        public var fwd: [Bool] = []
        public var nodes: [Int]
        public var lengthM = 0.0
        public var riseM = 0.0
        public var blocks = 1
    }

    /// Group consecutive route edges with the same display name.
    public func legs(_ route: Route) -> [Leg] {
        var out: [Leg] = []
        for (i, ei) in route.edges.enumerated() {
            let fwd = route.forward[i]
            let e = graph.edges[ei]
            let name = displayName(e)
            let a = route.nodes[i], b = route.nodes[i + 1]
            if out.isEmpty || out[out.count - 1].street != name {
                out.append(Leg(street: name, nodes: [a]))
            }
            let li = out.count - 1
            out[li].edges.append(ei)
            out[li].fwd.append(fwd)
            out[li].nodes.append(b)
            out[li].lengthM += e.lengthM
            let grade = fwd ? e.gradePct : -e.gradePct
            out[li].riseM += grade / 100.0 * e.lengthM
        }
        out = mergePingpong(out)
        for i in out.indices {
            out[i].blocks = max(1, out[i].nodes.dropFirst().filter { graph.degree[$0] >= 3 }.count)
        }
        return out
    }

    public static let pingpongMaxM = 120.0

    /// A short unnamed leg between two legs of the same named street is that street to a person
    /// (OSM sidewalks and service stubs). Mirrors cues.py `_merge_pingpong` exactly.
    func mergePingpong(_ legs: [Leg]) -> [Leg] {
        let t = config.templates
        let unnamed: Set<String> = [t.unnamedStreet, t.unnamedPath]
        var out = legs
        var i = 1
        while i < out.count - 1 {
            let mid = out[i], prev = out[i - 1], nxt = out[i + 1]
            if unnamed.contains(mid.street) && mid.lengthM < Cues.pingpongMaxM && prev.street == nxt.street
                && !unnamed.contains(prev.street) {
                for leg in [mid, nxt] {
                    out[i - 1].edges += leg.edges
                    out[i - 1].fwd += leg.fwd
                    out[i - 1].nodes += leg.nodes.dropFirst()
                    out[i - 1].lengthM += leg.lengthM
                    out[i - 1].riseM += leg.riseM
                }
                out.removeSubrange(i...(i + 1))
            } else {
                i += 1
            }
        }
        return out
    }

    public func buildCues(_ route: Route, refugeName: String) -> [Cue] {
        let t = config.templates
        if route.edges.isEmpty {
            return [fill("arrive", ["refuge": .str(refugeName)], distance: 0.0, node: route.nodes[0])]
        }
        var cues: [Cue] = []
        var dist = 0.0
        let lg = legs(route)
        for (li, leg) in lg.enumerated() {
            let startNode = leg.nodes[0]
            let d1 = Py.round(dist, 1)
            if li == 0 {
                let b = graph.edgeBearing(leg.edges[0], leg.fwd[0])
                cues.append(fill("start", ["street": .str(leg.street), "direction": .str(Geo.directionWord(b, t.directions))],
                                 distance: d1, node: startNode))
            } else {
                let prev = lg[li - 1]
                let bIn = graph.edgeBearing(prev.edges[prev.edges.count - 1], prev.fwd[prev.fwd.count - 1])
                let bOut = graph.edgeBearing(leg.edges[0], leg.fwd[0])
                let d = Geo.signedTurn(bIn, bOut)
                let side = d > 0 ? "right" : "left"
                let ad = abs(d)
                let c: Cue
                if ad < 30 {
                    c = fill("continue", ["street": .str(leg.street)], distance: d1, node: startNode)
                } else if ad < 60 {
                    c = fill("turn_slight", ["side": .str(side), "street": .str(leg.street)], distance: d1, node: startNode)
                } else if ad < 150 {
                    c = fill("turn", ["side": .str(side), "street": .str(leg.street)], distance: d1, node: startNode)
                } else {
                    c = fill("turn_sharp", ["side": .str(side), "street": .str(leg.street)], distance: d1, node: startNode)
                }
                cues.append(c)
            }
            if leg.blocks >= 2 {
                cues.append(fill("keep_blocks", ["street": .str(leg.street), "n": .int(leg.blocks)], distance: d1, node: startNode))
            } else {
                cues.append(fill("keep_meters", ["street": .str(leg.street), "n": .int(Cues.roundMeters(leg.lengthM))],
                                 distance: d1, node: startNode))
            }
            let avg = leg.lengthM > 0 ? abs(leg.riseM) / leg.lengthM * 100.0 : 0.0
            if leg.lengthM >= Cues.slopeMinLenM && avg >= Cues.slopeMinPct {
                cues.append(fill(leg.riseM < 0 ? "downhill" : "uphill", ["n": .int(Cues.roundMeters(leg.lengthM))],
                                 distance: d1, node: startNode))
            }
            dist += leg.lengthM
        }
        cues.append(fill("arrive", ["refuge": .str(refugeName)], distance: Py.round(dist, 1), node: route.nodes[route.nodes.count - 1]))
        return cues
    }

    static func mergeKeep(_ turnText: String, _ keep: Cue) -> String {
        let n = keep.vars["n"]?.description ?? ""
        if keep.template == "keep_blocks" { return "\(turnText) Keep going for \(n) blocks." }
        return "\(turnText) Keep going for \(n) meters."
    }

    public static let cardMaxWords = 90
    public static let cardMinSteps = 4
    public static let chainHopM = 200
    static let ontoRe = try! NSRegularExpression(pattern: "^(?:Turn (?:slight |sharp )?(?:left|right)|Continue) onto (.+?)\\.?$")

    struct Seg { var turn: String; var keepText: String?; var keepM: Int; var arrive: Bool }

    static func onto(_ text: String) -> String? {
        let r = NSRange(text.startIndex..., in: text)
        guard let m = ontoRe.firstMatch(in: text, range: r), let g = Range(m.range(at: 1), in: text) else { return nil }
        return String(text[g])
    }

    static func segments(_ cues: [Cue]) -> [Seg] {
        var segs: [Seg] = []
        let core = cues.filter { $0.template != "downhill" && $0.template != "uphill" }
        var i = 0
        while i < core.count {
            let c = core[i]
            let nxt: Cue? = i + 1 < core.count ? core[i + 1] : nil
            var seg = Seg(turn: c.text, keepText: nil, keepM: 0, arrive: c.template == "arrive")
            if !seg.arrive, let nxt, nxt.template == "keep_blocks" || nxt.template == "keep_meters" {
                let n = nxt.vars["n"]?.intValue ?? 0
                seg.keepText = mergeKeep("", nxt).trimmingCharacters(in: .whitespaces)
                seg.keepM = nxt.template == "keep_meters" ? n : n * 100
                i += 1
            }
            segs.append(seg)
            i += 1
        }
        return segs
    }

    static func weight(_ step: [Seg]) -> Int {
        step.last!.arrive ? 1_000_000_000 : step.reduce(0) { $0 + $1.keepM }
    }

    static func flush(_ chain: [String], _ last: Seg) -> String {
        var text = chain[0] + chain.dropFirst().map { ", then " + $0 }.joined() + "."
        if let k = last.keepText, last.keepM >= chainHopM || chain.count == 1 { text += " " + k }
        return text
    }

    static func render(_ step: [Seg], compact: Bool) -> String {
        if !compact {
            return step.map { $0.turn + ($0.keepText.map { " " + $0 } ?? "") }.joined(separator: " ")
        }
        var out: [String] = []
        var chain: [String]? = nil
        var prev: Seg? = nil
        var headOnto = false
        for s in step {
            let m = prev != nil ? onto(s.turn) : nil
            if let m, headOnto, let p = prev, p.keepM < chainHopM {
                chain!.append(m)
            } else {
                if let ch = chain, let p = prev { out.append(flush(ch, p)) }
                var head = s.turn
                if head.hasSuffix(".") { head.removeLast() }
                chain = [head]
                headOnto = onto(s.turn) != nil
            }
            prev = s
        }
        out.append(flush(chain!, prev!))
        return out.joined(separator: " ")
    }

    static func words(_ steps: [[Seg]], compact: Bool) -> Int {
        steps.reduce(0) { $0 + render($1, compact: compact).split(separator: " ").count }
    }

    static func mergeShortest(_ steps: inout [[Seg]]) {
        var bestJ = -1, bestW = 0
        for j in 1..<(steps.count - 1) {
            let w = weight(steps[j - 1]) + weight(steps[j])
            if bestJ < 0 || w < bestW { bestJ = j; bestW = w }
        }
        steps[bestJ - 1] += steps[bestJ]
        steps.remove(at: bestJ)
    }

    /// 4-7 plain steps for the printed card. Port of cues.py `card_steps`: merge the shortest hops first; long OSM
    /// routes are held to a word budget by chaining short hops ("Turn left onto Gate Lane, then Cabernet Lane.").
    public static func cardSteps(_ cues: [Cue], maxSteps: Int = 7, maxWords: Int? = cardMaxWords) -> [String] {
        var steps: [[Seg]] = segments(cues).map { [$0] }
        while steps.count > maxSteps { mergeShortest(&steps) }
        var compact = false
        if let maxWords, words(steps, compact: false) > maxWords {
            compact = true
            while words(steps, compact: true) > maxWords && steps.count > cardMinSteps { mergeShortest(&steps) }
        }
        return steps.map { render($0, compact: compact) }
    }

    /// Every turn template instantiated with these street names (what Cartesia pre-generates after a re-plan).
    public func allCueTexts(streets: [String], refugeNames: [String]) -> Set<String> {
        var out = Set<String>()
        for s in streets {
            out.insert(config.template("continue", ["street": s]))
            for side in ["left", "right"] {
                for key in ["turn_slight", "turn", "turn_sharp"] {
                    out.insert(config.template(key, ["side": side, "street": s]))
                }
            }
            for d in config.templates.directions {
                out.insert(config.template("start", ["street": s, "direction": d]))
            }
        }
        for r in refugeNames {
            out.insert(config.template("arrive", ["refuge": r]))
            out.insert(config.template("arrived", ["refuge": r]))
            out.insert(config.template("arrived_building", ["refuge": r]))
        }
        return out
    }
}
