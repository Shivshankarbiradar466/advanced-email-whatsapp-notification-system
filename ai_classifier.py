class EmailAIClassifier:

    def __init__(self):
        self.categories = {
            "Security": [
                "security", "password", "login", "signin",
                "verification", "verify", "otp", "account",
                "suspicious", "alert", "unauthorized", "breach"
            ],
            "Job/Internship": [
                "job", "career", "internship", "intern",
                "hiring", "recruitment", "placement",
                "resume", "interview", "vacancy", "employment"
            ],
            "Important": [
                "important", "urgent", "deadline",
                "action required", "notice", "warning",
                "payment", "invoice", "document"
            ],
            "Promotion": [
                "offer", "discount", "sale", "deal",
                "coupon", "promotion", "newsletter", "marketing"
            ],
            "Social": [
                "facebook", "instagram", "linkedin",
                "twitter", "social", "friend", "follow"
            ]
        }

        self.high_priority_words = [
            "urgent", "immediately", "critical", "security alert",
            "account compromised", "action required", "deadline",
            "payment due", "verification required"
        ]

    def classify(self, sender="", subject="", body=""):
        sender = sender or ""
        subject = subject or ""
        body = body or ""

        text = f"{sender} {subject} {body}".lower()
        scores = {}

        for category, keywords in self.categories.items():
            score = 0
            for keyword in keywords:
                if keyword.lower() in text:
                    score += 1
                    if keyword.lower() in subject.lower():
                        score += 1
            scores[category] = score

        best_category = max(scores, key=scores.get)
        best_score = scores[best_category]

        if best_score == 0:
            best_category = "General"
            confidence = 0.50
            reason = "No strong category keywords were detected."
        else:
            total = sum(scores.values())
            confidence = min(
                0.99,
                0.60 + (best_score / max(total, 1)) * 0.39
            )

            matched = [
                word
                for word in self.categories[best_category]
                if word.lower() in text
            ]

            reason = (
                f"Detected keywords: {', '.join(matched[:5])}"
                if matched
                else "Category matched using email content."
            )

        priority = self.detect_priority(subject, body)

        return (
            best_category,
            priority,
            round(confidence, 2),
            reason
        )

    def detect_priority(self, subject="", body=""):
        text = f"{subject} {body}".lower()

        for word in self.high_priority_words:
            if word in text:
                return "HIGH"

        medium_words = [
            "important", "reminder", "notification",
            "interview", "application", "deadline"
        ]

        for word in medium_words:
            if word in text:
                return "MEDIUM"

        return "NORMAL"

    def analyze(self, sender="", subject="", body=""):
        category, priority, confidence, reason = self.classify(
            sender,
            subject,
            body
        )

        return {
            "category": category,
            "priority": priority,
            "confidence": confidence,
            "reason": reason
        }