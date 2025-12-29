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
            A free, open-source tool to help your LaTeX resume get past ATS systems. Because job applications shouldn&apos;t be this hard.
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
              <CardTitle>ATS Keyword Optimization</CardTitle>
              <CardDescription>
                Automatically incorporates relevant keywords from job descriptions
              </CardDescription>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">
                The AI analyzes your resume and the job description, then rephrases bullet points to naturally incorporate relevant keywords while keeping your original content intact.
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Page Count Control</CardTitle>
              <CardDescription>
                Ensures your resume fits your target page count
              </CardDescription>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">
                Using a compile-and-feedback loop, TailorTom helps your resume fit within your target page count, condensing content when needed.
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>No Hallucination</CardTitle>
              <CardDescription>
                Only rephrases existing content - never invents new experiences
              </CardDescription>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">
                TailorTom only rephrases what you&apos;ve already written - it never invents new experiences or skills. Your content stays authentic and accurate.
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Diff Visualization</CardTitle>
              <CardDescription>
                See exactly what changed between original and optimized versions
              </CardDescription>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">
                See exactly what changed with detailed diff comparisons, showing word-level modifications so you know what was tweaked.
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>PDF Export</CardTitle>
              <CardDescription>
                Get both optimized LaTeX source and compiled PDF
              </CardDescription>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">
                Download your optimized resume as a PDF, or edit the LaTeX source directly in the app if you want to make tweaks before downloading.
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Easy to Use</CardTitle>
              <CardDescription>
                Simple workflow for managing multiple optimization jobs
              </CardDescription>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">
                Queue multiple jobs, track progress, and manage all your optimized resumes in one place.
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
                Upload your LaTeX resume template and configure your preferences (target pages, max iterations).
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
                The AI analyzes your resume and the job description, then optimizes your content for ATS compatibility while keeping your content authentic.
              </p>
            </div>
          </div>

          <div className="flex gap-4">
            <div className="flex-shrink-0 w-10 h-10 rounded-full bg-blue-600 text-white flex items-center justify-center font-bold">
              4
            </div>
            <div>
              <h3 className="text-xl font-semibold mb-2">Review & Download</h3>
              <p className="text-muted-foreground">
                Review the optimized resume, see what changed, make any final edits if needed, and download the PDF ready to submit.
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
              I built TailorTom as a fun side project after realizing how frustrating it is to get past ATS systems. 
              It&apos;s incredibly disheartening when great candidates never get their resumes seen because an automated 
              system filtered them out. So I decided to build something that could help.
            </p>
            <p className="text-muted-foreground">
              This is completely free and open source. I wanted to make it available to anyone who needs it, 
              because job searching is hard enough without having to game automated systems.
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
