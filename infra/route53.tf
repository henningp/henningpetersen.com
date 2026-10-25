# Route 53 public hosted zone.
#
# This moves DNS authority for the domain *away* from Host Europe and into AWS.
# Creating the zone is non-disruptive on its own: the domain keeps using
# Host Europe's nameservers until you point the registrar / Host Europe's
# "NS Delegate" field at `aws_route53_zone.site.name_servers` (4 servers, shown
# as `terraform output route53_name_servers`). Only at that moment does Route 53
# become authoritative.
#
# ORDER MATTERS: apply this whole file (zone + every record) FIRST, then flip
# the NS delegate. If you delegate before all records exist here, mail breaks.
resource "aws_route53_zone" "site" {
  name = var.domain
  tags = var.tags
}

# Apex "forward": a Route 53 alias is the only way to point the apex at CloudFront
# while still keeping the MX records, because a bare apex can't take a CNAME/ALIAS
# that coexists with MX. Route 53 A/AAAA aliases bypass that RFC limitation.
#
# This FLATTENS the apex onto the distribution -- https://henningpetersen.com/
# serves the same page as www. A <link rel="canonical" href="https://www.…"> on
# the page consolidates SEO onto the www subdomain. For a hard HTTP 301 instead,
# add a CloudFront Function on the same distribution; not needed for a placeholder.
resource "aws_route53_record" "apex_a" {
  zone_id = aws_route53_zone.site.id
  name    = var.domain
  type    = "A"

  allow_overwrite = true

  alias {
    name                   = aws_cloudfront_distribution.site.domain_name
    zone_id                = aws_cloudfront_distribution.site.hosted_zone_id
    evaluate_target_health = false
  }
}

resource "aws_route53_record" "apex_aaaa" {
  zone_id = aws_route53_zone.site.id
  name    = var.domain
  type    = "AAAA"

  allow_overwrite = true

  alias {
    name                   = aws_cloudfront_distribution.site.domain_name
    zone_id                = aws_cloudfront_distribution.site.hosted_zone_id
    evaluate_target_health = false
  }
}

# www is a subdomain, so a plain CNAME is fine.
resource "aws_route53_record" "www" {
  zone_id = aws_route53_zone.site.id
  name    = "www.${var.domain}"
  type    = "CNAME"

  allow_overwrite = true
  ttl             = 300
  records         = [aws_cloudfront_distribution.site.domain_name]
}

# Google-managed mail. Copy of the current record set -- keep in sync with Google.
resource "aws_route53_record" "mx" {
  zone_id = aws_route53_zone.site.id
  name    = var.domain
  type    = "MX"

  allow_overwrite = true
  ttl             = 300
  records = [
    "1  aspmx.l.google.com",
    "10 aspmx2.googlemail.com",
    "10 aspmx3.googlemail.com",
    "10 aspmx4.googlemail.com",
    "10 aspmx5.googlemail.com",
    "5  alt1.aspmx.l.google.com",
    "5  alt2.aspmx.l.google.com",
  ]
}

# All TXTs that live at the APEX must be in ONE `allow_overwrite` record.
# Route 53's allow_overwrite rewrites every TXT-at-a-name, so splitting the
# site-verification and SPF across two apex records would let the last-one-applied
# wipe the other. They are combined here.
resource "aws_route53_record" "txt_apex" {
  zone_id = aws_route53_zone.site.id
  name    = var.domain
  type    = "TXT"

  allow_overwrite = true
  ttl             = 300
  records = [
    "google-site-verification=BoQs6QNzSt3DivwKSiX_Dyaw21QWYms4Tct2JI7e0y0",
    "google-site-verification=CWm99Xtz1tXM6zXDFKeOMR5C7mmtQXf4K_4hNqbxQuY",
    "v=spf1 include:_spf.google.com -all",
  ]
}

# DMARC lives on its own name (_dmarc), so no apex collision -- allow_overwrite
# just guards re-application.
#
# p=reject asks receivers to reject mail that fails DMARC. Legitimate senders
# must pass aligned DKIM or SPF. Keep aggregate reports enabled for monitoring.
resource "aws_route53_record" "dmarc" {
  zone_id = aws_route53_zone.site.id
  name    = "_dmarc.${var.domain}"
  type    = "TXT"

  allow_overwrite = true
  ttl             = 300
  records = [
    "v=DMARC1; p=reject; pct=100; rua=mailto:hp@henningpetersen.com",
  ]
}
# Google DKIM: one TXT record containing two ordered character-strings.
# Each chunk must be <=255 bytes. Keep both quoted chunks in ONE records entry;
# separate entries create independent TXT records, which DKIM does not join.
resource "aws_route53_record" "dkim_google" {
  zone_id         = aws_route53_zone.site.id
  name            = "google._domainkey.${var.domain}"
  type            = "TXT"
  allow_overwrite = true
  ttl             = 300
  records = [
    "v=DKIM1; k=rsa; p=MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAtTDveBefC7aG8D2sJQRLSWN1duIiWYQnkWhr7KHWzzQYdSQQaNFvjSqgAuzdhznubwQ0kA1FWx3gdUI6UD3YmLfGfFGb4/WlmMiTbgcgvBg9klDdiqQHDXPU+rU9b/B5ozTUNFLGF8nZbGQnvmFXJFWQ4pEZ8RFaHpMJI6nfbXOUaVhbpc27OCTwSSlsHrSdn\"\"+l+HIuN0droxmQSJJAnwyQUG/oxHgX3I5yG51UmfFJG0YASnmjcrpqUwJXGf3lB+FXK5a4qFSrQpcLcNwuUhZbDwP+KtkEqXubukDs+hx0eyhcOvCGdcVvS0iSQZs4fCeFaVe8N0n/WzzD4o9zDiQIDAQAB",
  ]
}
