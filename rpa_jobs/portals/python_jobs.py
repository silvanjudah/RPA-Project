"""Adapter for the official python.org job board.

The board is public, has a clear listings page and per-job detail pages, and
its robots.txt allows /jobs/. The adapter paginates with ``?page=N`` and can
optionally open detail pages for the description / external apply link.
"""

from __future__ import annotations

from bs4 import NavigableString

from ..filters import matches_countries
from ..http_client import FetchError
from ..models import JobPosting
from .base import BasePortal, BusinessError


class PythonJobsPortal(BasePortal):
    name = "python-jobs"
    label = "Python.org Job Board (real portal)"

    def discover(self, limit: int) -> list[JobPosting]:
        max_pages = max(1, int(self.settings.get("max_pages", 1)))
        countries = self.country_filter()
        jobs: list[JobPosting] = []
        seen_urls: set[str] = set()

        for page in range(1, max_pages + 1):
            if len(jobs) >= limit:
                break
            page_url = self.base_url if page == 1 else f"{self.base_url}?page={page}"
            try:
                html = self.http.get(page_url)
            except FetchError as exc:
                if page == 1:
                    raise BusinessError(
                        f"python.org job board could not be read: {exc}"
                    ) from exc
                # The board now serves every job on one page and answers 404
                # for ?page=2, so stop paginating instead of failing the run.
                self.log.info("No page %d on python.org (%s) - pagination finished", page, exc)
                break
            soup = self.soup(html)
            cards = soup.select(self.selector("card", "ol.list-recent-jobs > li"))
            if not cards:
                if page == 1:
                    raise BusinessError(
                        "No vacancies found on the python.org job board - markup may have changed."
                    )
                break

            for card in cards:
                if len(jobs) >= limit:
                    break
                title_node = card.select_one(self.selector("title", "h2.listing-company a"))
                title = self.text(title_node)
                if not title:
                    continue

                company = self._company(card, title)
                location = self.text(card.select_one(self.selector("location", ".listing-location")))
                posted = self.date_from(card.select_one(self.selector("date", "time")))
                types = [
                    self.text(node)
                    for node in card.select(self.selector("types", ".listing-job-type a"))
                ]
                category = self.text(
                    card.select_one(self.selector("category", ".listing-company-category a"))
                )

                source = self.url(self.link_from(title_node))
                if source in seen_urls:
                    continue
                seen_urls.add(source)

                job = JobPosting(
                    portal=self.name,
                    title=title,
                    company=company,
                    location=location,
                    posted_date=posted,
                    category=category or ", ".join(types),
                    source_url=source,
                    apply_url=source,
                )
                if countries and not matches_countries(job, countries):
                    continue
                jobs.append(job)
        return jobs

    def enrich(self, job: JobPosting) -> JobPosting:
        if not job.source_url:
            return job
        soup = self.soup(self.http.get(job.source_url))

        description_node = soup.select_one(
            self.selector("detail_description", "div.job-description")
        )
        if description_node:
            job.description = self.text(description_node)

        apply_url = self._pick_apply_link(description_node)
        if apply_url:
            job.apply_url = apply_url

        if not job.description:
            self.log.debug("No detail description found for %s", job.source_url)
        return job

    # ----------------------------------------------------------------- helpers
    def _pick_apply_link(self, node) -> str:
        """Prefer an anchor whose text mentions applying/careers/jobs."""
        if node is None:
            return ""
        selector = self.selectors.get("detail_apply_link") or "a[href^='http']"
        anchors = node.select(selector)
        fallback = ""
        for anchor in anchors:
            href = self.link_from(anchor)
            if not href or "python.org" in href:
                continue
            label = self.text(anchor).lower()
            if any(word in label for word in ("apply", "career", "job", "position")):
                return href
            fallback = fallback or href
        return fallback

    def _company(self, card, title: str) -> str:
        span = card.select_one(self.selector("company_name", ".listing-company-name"))
        if span is not None:
            br = span.find("br")
            if br is not None and isinstance(br.next_sibling, NavigableString):
                company = self.text(br.next_sibling)
                if company:
                    return company
            # Fallback: full span text minus the title and the "New" badge.
            raw = self.text(span)
            for noise in (title, "New"):
                raw = raw.replace(noise, " ")
            return self.text(raw)
        return ""
