"""Published knowledge files seeded for every tenant."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PublishedDocument:
    """A product file and the title customers see on a citation."""

    source_uri: str
    title: str


PUBLISHED_DOCUMENTS: tuple[PublishedDocument, ...] = (
    PublishedDocument("knowledge/policies/return-policy.md", "Return policy"),
    PublishedDocument("knowledge/policies/refund-policy.md", "Refund policy"),
    PublishedDocument("knowledge/policies/shipping-policy.md", "Shipping policy"),
    PublishedDocument("knowledge/policies/account-security.md", "Account security"),
    PublishedDocument("knowledge/product-docs/product-faq.md", "Product FAQ"),
    PublishedDocument("knowledge/product-docs/support-playbook.md", "Support playbook"),
)
