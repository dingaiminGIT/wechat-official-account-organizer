// swift-tools-version: 5.9
import PackageDescription
let package = Package(name: "WeChatOrganizer", platforms: [.macOS(.v14)], products: [.executable(name: "WeChatOrganizer", targets: ["WeChatOrganizer"])], targets: [.executableTarget(name: "WeChatOrganizer")])
