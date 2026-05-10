package com.streamflix.app;

import android.os.Bundle;
import android.view.WindowManager;
import android.webkit.PermissionRequest;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import com.getcapacitor.BridgeActivity;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;

public class MainActivity extends BridgeActivity {

    private static final Set<String> BLOCKED_DOMAINS = new HashSet<>(Arrays.asList(
        "doubleclick.net","googlesyndication.com","googletagmanager.com","googleadservices.com",
        "google-analytics.com","adservice.google.com","pagead2.googlesyndication.com",
        "ads.yahoo.com","advertising.com","adnxs.com","adsrvr.org","adform.net","adroll.com",
        "criteo.com","rubiconproject.com","openx.net","pubmatic.com","appnexus.com",
        "smartadserver.com","taboola.com","outbrain.com","mgid.com","sharethrough.com",
        "bidswitch.net","exoclick.com","trafficjunky.com","juicyads.com","propellerads.com",
        "popads.net","adsterra.com","clickadu.com","adcash.com","yllix.com","trafficstars.com",
        "hotjar.com","mixpanel.com","coin-hive.com","coinhive.com","facebook.net","connect.facebook.net"
    ));

    private static final String[] BLOCKED_PATTERNS = {"/ads/","popunder","tracker","pixel.","beacon"};

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        WebView wv = getBridge().getWebView();
        WebSettings ws = wv.getSettings();
        ws.setJavaScriptEnabled(true);
        ws.setDomStorageEnabled(true);
        ws.setMediaPlaybackRequiresUserGesture(false);
        ws.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);

        wv.setWebViewClient(new WebViewClient() {
            @Override
            public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                String url = request.getUrl().toString();
                String host = request.getUrl().getHost();
                if (host != null) {
                    for (String domain : BLOCKED_DOMAINS) {
                        if (host.endsWith(domain)) return emptyResponse();
                    }
                }
                for (String pat : BLOCKED_PATTERNS) {
                    if (url.contains(pat)) return emptyResponse();
                }
                return super.shouldInterceptRequest(view, request);
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                super.onPageFinished(view, url);
                view.evaluateJavascript(
                    "(function(){" +
                    "window.open=function(){return null;};" +
                    "window.alert=function(){};" +
                    "window.confirm=function(){return true;};" +
                    "function rm(){document.querySelectorAll('*').forEach(function(e){" +
                    "try{var s=window.getComputedStyle(e),z=parseInt(s.zIndex)||0,p=s.position,t=e.tagName||'';" +
                    "if(z>9000&&(p==='fixed'||p==='absolute')&&t!=='VIDEO'&&t!=='IFRAME'){e.remove();}}catch(x){}});" +
                    "}setInterval(rm,1500);rm();" +
                    "document.addEventListener('click',function(e){" +
                    "var a=e.target.closest&&e.target.closest('a');" +
                    "if(a&&a.target==='_blank'){e.preventDefault();e.stopPropagation();}},true);" +
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

        wv.loadUrl("https://streamflix-production-9559.up.railway.app/app");
    }

    private WebResourceResponse emptyResponse() {
        return new WebResourceResponse("text/plain", "utf-8",
            new java.io.ByteArrayInputStream(new byte[0]));
    }
}
