import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App as AntdApp, ConfigProvider, theme as antdTheme } from "antd";
import { createRoot } from "react-dom/client";
import { ProductApp } from "./ProductApp";
import "./styles.css";
import { ThemeProvider, useTheme } from "./theme";

const queryClient = new QueryClient();

function ThemedApp() {
  const { darkMode } = useTheme();
  return <ConfigProvider theme={{ algorithm: darkMode ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm, token: { colorPrimary: "#e60012", colorError: "#c9000b", borderRadius: 8, fontFamily: "Inter, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif" }, components: { Button: { controlHeight: 34 }, Input: { controlHeight: 36 }, Select: { controlHeight: 36 } } }}>
    <AntdApp>
      <ProductApp />
    </AntdApp>
  </ConfigProvider>;
}

createRoot(document.getElementById("root")!).render(
  <QueryClientProvider client={queryClient}>
    <ThemeProvider>
      <ThemedApp />
    </ThemeProvider>
  </QueryClientProvider>,
);
