const { spawn } = require("node:child_process");
const { once } = require("node:events");
const { appendFileSync } = require("node:fs");
const { constants } = require("node:os");
const { createInterface } = require("node:readline");

const clock = new Intl.DateTimeFormat("en-GB", {
  timeZone: process.env.LOG_TZ ?? "Asia/Seoul",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  fractionalSecondDigits: 3,
  hourCycle: "h23",
  timeZoneName: "longOffset",
});

const [command, ...args] = process.argv.slice(2);
const child = spawn(command, args, {
  stdio: ["inherit", "pipe", "pipe"],
  // The Node base image's node user runs Next.js. Only the logger needs write access.
  ...(process.env.APP_RUN_AS_NODE === "1" && { uid: 1000, gid: 1000 }),
});

let reportedWriteFailure = false;

function timestamp() {
  const parts = Object.fromEntries(clock.formatToParts(new Date()).map(({ type, value }) => [type, value]));
  const date = `${parts.year}-${parts.month}-${parts.day}`;
  const offset = parts.timeZoneName.slice(3) || "Z";
  return { date, time: `${date}T${parts.hour}:${parts.minute}:${parts.second}.${parts.fractionalSecond}${offset}` };
}

function writeLine(output, line) {
  const { date, time } = timestamp();
  const message = `[${time}] ${line}\n`;
  try {
    appendFileSync(`/var/log/app/${date}.log`, message);
    reportedWriteFailure = false;
  } catch (error) {
    if (!reportedWriteFailure) {
      process.stderr.write(`[${time}] Cannot write application log: ${error.message}\n`);
      reportedWriteFailure = true;
    }
  }
  return output.write(message);
}

async function forward(input, output) {
  const lines = createInterface({ input, crlfDelay: Infinity });
  for await (const line of lines) {
    if (!writeLine(output, line)) await once(output, "drain");
  }
}

Promise.all([forward(child.stdout, process.stdout), forward(child.stderr, process.stderr)]).catch((error) => {
  writeLine(process.stderr, `Cannot forward application log: ${error.message}`);
  child.kill("SIGTERM");
  process.exitCode = 1;
});

for (const signal of ["SIGTERM", "SIGINT"]) {
  process.on(signal, () => child.kill(signal));
}

child.on("error", (error) => {
  writeLine(process.stderr, `Cannot start ${command}: ${error.message}`);
  process.exitCode = 1;
});

child.on("close", (code, signal) => {
  process.exitCode ??= code ?? (128 + constants.signals[signal]);
});
