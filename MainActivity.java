package com.fenixtv.app;

import android.os.Bundle;
import android.net.wifi.WifiInfo;
import android.net.wifi.WifiManager;
import android.content.Context;
import android.provider.Settings;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;
import android.webkit.PermissionRequest;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {

    private String deviceMAC = null;

    // Interface expuesta a JavaScript para obtener la MAC
    public class AndroidInterface {
        @JavascriptInterface
        public String getMAC() {
            return deviceMAC != null ? deviceMAC : "";
        }
    }

    private String getDeviceMAC() {
        // Android ID como identificador único estable
        String androidId = Settings.Secure.getString(
            getContentResolver(), Settings.Secure.ANDROID_ID
        );
        if (androidId != null && !androidId.equals("9774d56d682e549c")) {
            // Formatear como MAC a partir del Android ID
            String hex = androidId.toUpperCase();
            while (hex.length() < 12) hex = "0" + hex;
            hex = hex.substring(0, 12);
            return hex.substring(0,2)+":"+hex.substring(2,4)+":"+hex.substring(4,6)+
                   ":"+hex.substring(6,8)+":"+hex.substring(8,10)+":"+hex.substring(10,12);
        }
        return null;
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        deviceMAC = getDeviceMAC();

        WebView wv = getBridge().getWebView();
        WebSettings ws = wv.getSettings();
        ws.setJavaScriptEnabled(true);
        ws.setDomStorageEnabled(true);
        ws.setMediaPlaybackRequiresUserGesture(false);
        ws.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);

        // Exponer la MAC a JavaScript
        wv.addJavascriptInterface(new AndroidInterface(), "Android");

        wv.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageFinished(WebView view, String url) {
                super.onPageFinished(view, url);
                // Bloquear popups y ventanas nuevas
                view.evaluateJavascript(
                    "(function(){" +
                    "window.open=function(){return null;};" +
                    "window.alert=function(){};" +
                    "})();", null);
            }
        });

        wv.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onCreateWindow(WebView view, boolean isDialog, boolean isUserGesture, android.os.Message resultMsg) {
                return false;
            }
            @Override
            public void onPermissionRequest(PermissionRequest request) {
                request.grant(request.getResources());
            }
        });

        wv.loadUrl("https://streamflix-production-9559.up.railway.app/fenix");
    }
}
