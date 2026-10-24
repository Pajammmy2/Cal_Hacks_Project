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
        for i in out.indices {
            out[i].blocks = max(1, out[i].nodes.dropFirst().filter { graph.degree[$0] >= 3 }.count)
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

    /// 4-7 plain steps for the printed card: drop slope cues, fold each keep cue into its turn.
    public static func cardSteps(_ cues: [Cue], maxSteps: Int = 7) -> [String] {
        var steps: [(String, Int)] = []
        let core = cues.filter { $0.template != "downhill" && $0.template != "uphill" }
        var i = 0
        while i < core.count {
            let c = core[i]
            let nxt: Cue? = i + 1 < core.count ? core[i + 1] : nil
            if c.template != "arrive", let nxt, nxt.template == "keep_blocks" || nxt.template == "keep_meters" {
                let n = nxt.vars["n"]?.intValue ?? 0
                steps.append((mergeKeep(c.text, nxt), nxt.template == "keep_meters" ? n : n * 100))
                i += 2
            } else {
                steps.append((c.text, c.template == "arrive" ? 1_000_000_000 : 0))
                i += 1
            }
        }
        while steps.count > maxSteps {
            var bestJ = -1, bestW = 0
            for j in 1..<(steps.count - 1) {
                let w = steps[j - 1].1 + steps[j].1
                if bestJ < 0 || w < bestW { bestJ = j; bestW = w }
            }
            let a = steps[bestJ - 1], b = steps[bestJ]
            steps[bestJ - 1] = (a.0 + " " + b.0, a.1 + b.1)
            steps.remove(at: bestJ)
        }
        return steps.map(\.0)
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
