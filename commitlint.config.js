/**
 * commitlint configuration for company-research-agent
 *
 * Convention: Conventional Commits.
 * Reference: https://www.conventionalcommits.org/en/v1.0.0/
 *
 * Commit messages are written in English. Documentation is written in Spanish,
 * but commit messages, branch names and code identifiers are always English.
 */
module.exports = {
  extends: ['@commitlint/config-conventional'],
  rules: {
    'type-enum': [
      2,
      'always',
      [
        'feat',     // new feature
        'fix',      // bug fix
        'docs',     // documentation changes
        'style',    // formatting, missing semicolons, etc.
        'refactor', // code change that neither fixes a bug nor adds a feature
        'perf',     // performance improvement
        'test',     // adding or correcting tests
        'build',    // build system or external dependencies
        'ci',       // CI configuration
        'chore',    // other changes that don't modify src or test
        'revert',   // revert a previous commit
      ],
    ],
    // Permite minúsculas con siglas y nombres propios embebidos (CLAUDE.md, ADR, SDK,
    // PER, Langfuse, Pydantic); prohíbe subjects en Title Case, PascalCase, UPPER o Sentence case.
    'subject-case': [2, 'never', ['sentence-case', 'start-case', 'pascal-case', 'upper-case']],
    'subject-empty': [2, 'never'],
    'subject-full-stop': [2, 'never', '.'],
    'header-max-length': [2, 'always', 100],
    'body-leading-blank': [2, 'always'],
    'footer-leading-blank': [2, 'always'],
  },
};
