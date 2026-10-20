
from dataclasses import dataclass, field
from typing import Any, List


@dataclass
class RecommendationResult:
    root_cause: str
    explanation: str
    severity: str
    suggested_fixes: List[str] = field(default_factory=list)
    verification_steps: List[str] = field(default_factory=list)


def generate_recommendations(correlation: Any) -> RecommendationResult:
    """Generate safe, category-specific troubleshooting advice."""

    category = str(
        getattr(correlation, "probable_category", "UNDETERMINED")
    ).strip().upper()

    status = str(getattr(correlation, "status", "UNKNOWN")).upper()

    if status == "INSUFFICIENT_DATA" or category == "UNDETERMINED":
        return RecommendationResult(
            root_cause="Insufficient diagnostic data",
            explanation="More measurements are needed before identifying a probable issue.",
            severity="UNKNOWN",
            suggested_fixes=[
                "Continue monitoring to collect more measurements.",
                "Check gateway, internet, DNS and HTTP results.",
                "Avoid changing network settings until more evidence is available."
            ],
            verification_steps=[
                "Collect several monitoring cycles.",
                "Review the latest diagnosis and measurement history."
            ]
        )

    recommendations = {
        "LOCAL_GATEWAY_CONNECTIVITY": RecommendationResult(
            root_cause="Possible local gateway or router connectivity problem",
            explanation="The gateway was reported unreachable by the available measurements.",
            severity="HIGH",
            suggested_fixes=[
                "Check that the computer is connected to the correct Wi-Fi network.",
                "Check router power and connection indicators.",
                "Check whether other devices can reach the router.",
                "If the problem persists, inspect the local connection or contact the network administrator."
            ],
            verification_steps=[
                "Check gateway reachability over several monitoring cycles.",
                "Confirm that packet loss and latency improve."
            ]
        ),

        "DNS_RESOLUTION": RecommendationResult(
            root_cause="Possible DNS resolution problem",
            explanation="The diagnosis indicates DNS degradation and a failed DNS check.",
            severity="MEDIUM",
            suggested_fixes=[
                "Confirm that the internet connection is working.",
                "Open Command Prompt and run: nslookup google.com",
                "Check the configured DNS settings.",
                "If DNS continues to fail, contact the network administrator or ISP."
            ],
            verification_steps=[
                "Run nslookup google.com again.",
                "Check whether the application's DNS status becomes PASS.",
                "Compare DNS response times across monitoring cycles."
            ]
        ),

        "INTERNET_PATH_CONNECTIVITY": RecommendationResult(
            root_cause="Possible internet or upstream connectivity problem",
            explanation="Internet reachability failed without a confirmed gateway failure.",
            severity="HIGH",
            suggested_fixes=[
                "Check whether other devices on the same network can access the internet.",
                "Check the router's internet connection indicator.",
                "Compare reachability to more than one external destination.",
                "If multiple destinations and devices fail, contact the ISP."
            ],
            verification_steps=[
                "Confirm gateway reachability.",
                "Check external destination reachability.",
                "Verify that DNS and HTTP checks recover."
            ]
        ),

        "HTTP_DESTINATION_OR_SERVICE": RecommendationResult(
            root_cause="Possible website, destination service, or HTTP connectivity problem",
            explanation="DNS succeeded, but the HTTP status indicates a possible destination or HTTP-path issue.",
            severity="MEDIUM",
            suggested_fixes=[
                "Open the tested website in a browser.",
                "Check whether other websites are accessible.",
                "Verify the configured URL and HTTP status code.",
                "If only one destination fails, check that service before changing router settings."
            ],
            verification_steps=[
                "Repeat the HTTP/HTTPS check.",
                "Review the latest HTTP status code and response time.",
                "Compare with another destination if available."
            ]
        ),

        "NETWORK_PERFORMANCE_DEGRADATION": RecommendationResult(
            root_cause="Possible network performance degradation",
            explanation="High latency, packet loss, or jitter was detected in recent measurements.",
            severity="MEDIUM",
            suggested_fixes=[
                "Pause large downloads and uploads temporarily.",
                "If using Wi-Fi, move closer to the router.",
                "Check whether other devices experience the same slowdown.",
                "If performance remains poor, compare gateway and external-host measurements."
            ],
            verification_steps=[
                "Monitor latency, packet loss and jitter again.",
                "Compare gateway and external-host latency.",
                "Check whether the measurements improve over several cycles."
            ]
        ),

        "OTHER_OR_MIXED_DEGRADATION": RecommendationResult(
            root_cause="Possible mixed or unidentified network degradation",
            explanation="Degradation was detected, but the available evidence does not isolate one category.",
            severity="MEDIUM",
            suggested_fixes=[
                "Review the correlated symptoms and supporting evidence.",
                "Check gateway, internet, DNS and HTTP results separately.",
                "Avoid disruptive network changes until the symptoms are clearer."
            ],
            verification_steps=[
                "Collect additional monitoring measurements.",
                "Review whether one symptom becomes consistently dominant."
            ]
        ),

        "NO_PERSISTENT_DEGRADATION_DETECTED": RecommendationResult(
            root_cause="No persistent network degradation detected",
            explanation="The current analysis did not identify active persistent degradation. This does not guarantee that every connection is problem-free.",
            severity="LOW",
            suggested_fixes=[
                "No corrective action is currently indicated by the available evidence.",
                "Continue monitoring if intermittent problems were reported.",
                "Review the history if a slowdown occurs again."
            ],
            verification_steps=[
                "Confirm that gateway and internet connectivity remain available.",
                "Check that latency, packet loss, DNS and HTTP results remain stable."
            ]
        )
    }

    return recommendations.get(
        category,
        RecommendationResult(
            root_cause=category.replace("_", " ").title(),
            explanation="No specific recommendation rule matches this category yet.",
            severity="REVIEW",
            suggested_fixes=[
                "Review the supporting evidence.",
                "Collect more measurements before changing network settings."
            ],
            verification_steps=[
                "Run additional monitoring cycles.",
                "Compare the new measurements with the previous history."
            ]
        )
    )
