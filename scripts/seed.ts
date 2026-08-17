import { db } from "../src/lib/db";
import { hashPassword, DEFAULT_PASSWORD } from "../src/lib/password";

/**
 * Seeds the database with the initial admin account.
 *
 *   Name:     TheHacker
 *   Password: 1234
 *   Rang:     ADMIN
 *
 * The admin must change their password on the first login.
 *
 * Usage:  bun run seed
 */
async function main() {
  const adminName = "TheHacker";

  const existing = await db.user.findUnique({ where: { name: adminName } });

  if (existing) {
    // Keep the admin account idempotent: update the password hash + role
    // so re-running the seed always yields a known-good admin.
    const passwordHash = await hashPassword(DEFAULT_PASSWORD);
    await db.user.update({
      where: { name: adminName },
      data: {
        passwordHash,
        role: "ADMIN",
        mustChangePassword: true,
      },
    });
    console.log(`Admin "${adminName}" already existed - password reset to default.`);
  } else {
    const passwordHash = await hashPassword(DEFAULT_PASSWORD);
    await db.user.create({
      data: {
        name: adminName,
        passwordHash,
        role: "ADMIN",
        mustChangePassword: true,
      },
    });
    console.log(`Admin "${adminName}" created with default password.`);
  }
}

main()
  .then(async () => {
    await db.$disconnect();
    process.exit(0);
  })
  .catch(async (err) => {
    console.error("Seed failed:", err);
    await db.$disconnect();
    process.exit(1);
  });
