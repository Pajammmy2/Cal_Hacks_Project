import SwiftUI
import EmberApp

@main
struct EmberNavigatorApp: App {
    @StateObject private var model = AppModel()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(model)
                .onOpenURL { model.handleURL($0) }
        }
    }
}
