import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Github, Linkedin, Twitter } from "lucide-react";

export default function Home() {
  return (
    <div className="flex flex-col min-h-screen">
      {/* Hero Section */}
      <section className="container mx-auto px-4 py-16 max-w-6xl">
        <div className="text-center space-y-6">
          <h1 className="text-5xl font-bold tracking-tight">
            TailorTom
          </h1>
          <p className="text-xl text-muted-foreground max-w-2xl mx-auto">
            A free, open-source tool to get your resume past ATS. Use LaTeX or upload a Word doc—we optimize it for each job. Because applications shouldn&apos;t be this hard.
          </p>
          <div className="flex gap-4 justify-center pt-4">
            <Button asChild size="lg">
              <Link href="/settings">Get Started</Link>
            </Button>
            <Button asChild variant="outline" size="lg">
              <Link href="/jobs/new">Queue Optimization</Link>
            </Button>
          </div>
        </div>
      </section>

      {/* Features Section */}
      <section className="container mx-auto px-4 py-16 max-w-6xl">
        <h2 className="text-3xl font-bold text-center mb-12">Features</h2>
        <div className="grid md:grid-cols-3 gap-6">
          <Card>
            <CardHeader>
              <CardTitle>Word or LaTeX</CardTitle>
              <CardDescription>
                Upload a .docx or paste LaTeX—we convert and optimize
              </CardDescription>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">
                No LaTeX experience? Upload your Word resume and we&apos;ll convert it to LaTeX. Already use LaTeX? Paste it in. Either way, you get a single template optimized per job.
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>ATS Keyword Optimization</CardTitle>
              <CardDescription>
                Relevant keywords from job descriptions, no hallucination
              </CardDescription>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">
                The AI rephrases your bullet points to incorporate relevant keywords from the job description while keeping line counts and your original content intact. It never invents experiences.
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Line-Count Preservation</CardTitle>
              <CardDescription>
                Layout stays the same; only wording changes
              </CardDescription>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">
                We compile and verify: if a change would break your layout (e.g., 2 lines → 3), we revert and retry with feedback. Your page count and bullet lengths stay under your control.
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Diff &amp; PDF</CardTitle>
              <CardDescription>
                See what changed, then download
              </CardDescription>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">
                Side-by-side PDF comparison with highlights and word-level diffs. Edit LaTeX in the app, preview PDF on save and on load, and download when ready.
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Job Queue</CardTitle>
              <CardDescription>
                Multiple jobs, notifications, one place
              </CardDescription>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">
                Queue several optimizations, get desktop and in-app notifications when they finish, and manage everything from the Jobs page.
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Free &amp; Open Source</CardTitle>
              <CardDescription>
                No sign-up required; run locally or deploy yourself
              </CardDescription>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">
                TailorTom is MIT-licensed. Use it in the browser, self-host with your own API key, or contribute on GitHub.
              </p>
            </CardContent>
          </Card>
        </div>
      </section>

      {/* How It Works Section */}
      <section className="container mx-auto px-4 py-16 max-w-4xl">
        <h2 className="text-3xl font-bold text-center mb-12">How It Works</h2>
        <div className="space-y-8">
          <div className="flex gap-4">
            <div className="flex-shrink-0 w-10 h-10 rounded-full bg-blue-600 text-white flex items-center justify-center font-bold">
              1
            </div>
            <div>
              <h3 className="text-xl font-semibold mb-2">Set Up Your Resume</h3>
              <p className="text-muted-foreground">
                In Settings: paste LaTeX or upload a Word (.docx) resume. We convert Word to LaTeX and show a live PDF preview. Set target pages and optimization options.
              </p>
            </div>
          </div>

          <div className="flex gap-4">
            <div className="flex-shrink-0 w-10 h-10 rounded-full bg-blue-600 text-white flex items-center justify-center font-bold">
              2
            </div>
            <div>
              <h3 className="text-xl font-semibold mb-2">Paste Job Description</h3>
              <p className="text-muted-foreground">
                Paste the full job description for the position you&apos;re applying to. The more context, the better the optimization.
              </p>
            </div>
          </div>

          <div className="flex gap-4">
            <div className="flex-shrink-0 w-10 h-10 rounded-full bg-blue-600 text-white flex items-center justify-center font-bold">
              3
            </div>
            <div>
              <h3 className="text-xl font-semibold mb-2">AI Optimization</h3>
              <p className="text-sm text-muted-foreground">
                Our pipeline compiles your resume, extracts line-count constraints, and uses the AI to rephrase bullets with job keywords. It compiles again to verify layout and retries with feedback if needed.
              </p>
            </div>
          </div>

          <div className="flex gap-4">
            <div className="flex-shrink-0 w-10 h-10 rounded-full bg-blue-600 text-white flex items-center justify-center font-bold">
              4
            </div>
            <div>
              <h3 className="text-xl font-semibold mb-2">Review &amp; Download</h3>
              <p className="text-muted-foreground">
                View the diff, edit LaTeX if you want, and download the optimized PDF. Filenames use your name and the company so you can keep track.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* About Section */}
      <section className="container mx-auto px-4 py-16 max-w-4xl">
        <Card>
          <CardHeader>
            <CardTitle className="text-2xl">About TailorTom</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-muted-foreground">
              I built TailorTom after realizing how hard it is to get past ATS systems. Great candidates often never get seen because a bot filtered them out. So I built a tool that optimizes your resume for each job—whether you use LaTeX or Word—without inventing content or breaking your layout.
            </p>
            <p className="text-muted-foreground">
              It&apos;s free and open source. No sign-up required. Use it in the browser or self-host with your own API key. Job searching is hard enough without having to game automated systems.
            </p>
            <div className="pt-4 space-y-4">
              <div>
                <p className="font-semibold mb-2">Made by Ryan Amiri</p>
                <div className="flex gap-4">
                  <Link 
                    href="https://x.com/RyanAmiri__" 
                    target="_blank" 
                    rel="noopener noreferrer"
                    className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
                  >
                    <Twitter className="h-4 w-4" />
                    Twitter
                  </Link>
                  <Link 
                    href="https://www.linkedin.com/in/ryanamiri/" 
                    target="_blank" 
                    rel="noopener noreferrer"
                    className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
                  >
                    <Linkedin className="h-4 w-4" />
                    LinkedIn
                  </Link>
                  <Link 
                    href="https://github.com/ryankamiri/tailor-tom" 
                    target="_blank" 
                    rel="noopener noreferrer"
                    className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
                  >
                    <Github className="h-4 w-4" />
                    View on GitHub
                  </Link>
                </div>
              </div>
              <div className="pt-2 border-t">
                <p className="text-sm text-muted-foreground">
                  TailorTom is open source and available on GitHub. Contributions, issues, and feedback are welcome!
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      </section>
    </div>
  );
}
