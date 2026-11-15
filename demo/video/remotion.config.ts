import { Config } from "@remotion/cli/config";
// Use the Chrome already installed on this Mac (no headless-shell download).
Config.setBrowserExecutable("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome");
Config.setVideoImageFormat("jpeg");
Config.setJpegQuality(92);
Config.setConcurrency(6);
Config.setCodec("h264");
Config.setCrf(18);
